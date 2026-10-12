"""`TC-AUTHOR-20` (FR-AUTHOR-20, CT-PROV-10, P0) — the prompt pins (TS-159, #711).

Case: test plan §5.1 row 20; design delta §3.1 (FR-AUTHOR-20) and §4. The three version
constants — `AUTHOR_INVENTORY_TEMPLATE_V`, `AUTHOR_RUBRIC_TEMPLATE_V`,
`AUTHOR_GRADES_TEMPLATE_V` — ride every assembled request, so the provider's request key
(the sha256 of the request including the templates, `RecordedFixtureProvider`) changes the
moment a template is edited. The oracle, in the plan's order:

1. **Control**: AF-01 replays the corpus with **zero** misses — a control miss means the
   corpus coupling is off, not the pins.
2. **Ride**: each constant's value appears in some captured request payload (the fields'
   joined values; `PromptPayload.fields` is an ordered (name, value) sequence).
3. **Bump**: bumping each constant in turn changes the request key — the provider misses
   loudly (`FixtureMissingError`) and never replays the recorded success. The miss is
   observed at
   the provider boundary through a recording wrapper, not as an escaping exception:
   CT-AUTHOR-10 forbids `draft()` from raising once a document's text is extracted, and a
   provider error is FR-AUTHOR-05a's fallback trigger — the module is *supposed* to
   survive it. What must not happen is a **stale replay**: the bumped run resolves
   strictly fewer items than the control run.

Written ahead of #694 ("the report, summary, logging and prompt pins"), keyed
`#694 report logging` in `WRITTEN_AHEAD_BLOCKERS` — a `command` probe; see the registry
comment for why a `symbol` key on the three constants fires one story early (#692 ships
each reasoning step with its own prompt constant), and re-check the case green before
unmarking — never on the notice alone.

Rung 1, guards first (#689's module surface, then #686's corpus).
"""

from __future__ import annotations

import pytest

from aeh.prov import FixtureMissingError
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
)
from tests.support.impl import require, require_path


PINS = ("AUTHOR_INVENTORY_TEMPLATE_V", "AUTHOR_RUBRIC_TEMPLATE_V",
        "AUTHOR_GRADES_TEMPLATE_V")
PIN_ISSUE = "#694 report logging"


class _MissRecorder(CountingProvider):
    """The counting provider plus a memory of every loud miss.

    `CountingProvider.complete` records the call and delegates; this subclass wraps that
    delegation so a `FixtureMissingError` is recorded (payload, model ref, message) and
    re-raised — the module may fall back past a provider error (FR-AUTHOR-05a), so the
    miss is observable only at this boundary.
    """

    def __init__(self, inner) -> None:
        super().__init__(inner)
        self.misses: list[tuple] = []

    def complete(self, prompt, model_ref, params):
        try:
            return super().complete(prompt, model_ref, params)
        except FixtureMissingError as exc:
            self.misses.append((prompt, model_ref, str(exc)))
            raise


def _guards() -> tuple:
    author = require(AUTHOR_MODULE, issue=AUTHOR_ISSUE)  # the module itself
    require(AUTHOR_MODULE, *AUTHOR_SURFACE, issue=AUTHOR_ISSUE)  # the §3.1 names
    require(AUTHOR_MODULE, *PINS, issue=PIN_ISSUE)
    require_path(af("AF-01"), "the AF-01 authored fixture", issue=CORPUS_ISSUE)
    recordings = require_path(RECORDINGS, "the authoring recordings", issue=CORPUS_ISSUE)
    return author, recordings


def _payload_text(prompt) -> str:
    return "\n".join(value for _name, value in prompt.fields)


def _af01_draft(author, recordings, provider, output_dir):
    return make_service(author, chain_from_config(), provider).draft(
        documents=sorted(af("AF-01").glob("*.pdf")), output_dir=output_dir)


def test_tc_author_20_the_version_pins_ride_every_request(tmp_path, make_fixture_provider):
    """Control run over the corpus: zero misses; each pin's value appears in some captured
    request payload. The substring check assumes the constants are distinguishing strings
    (design §3.1 renders them into every request text); a landing that ships a bare
    version digit would need the rendered form here — a reconciliation, disclosed."""
    author, recordings = _guards()
    recorder = _MissRecorder(make_fixture_provider(recordings))
    result = _af01_draft(author, recordings, recorder, tmp_path / "af01")

    assert result.outcomes, "TC-AUTHOR-20: the control run produced no outcomes"
    assert recorder.misses == [], (
        f"TC-AUTHOR-20: the AF-01 control run missed {len(recorder.misses)} request(s) — "
        "the corpus coupling is off (see author_vocabulary.chain_from_config), not the "
        "pins; fix the control before reading the pin assertions")
    payloads = [_payload_text(prompt) for prompt, _ref, _params in recorder.calls]
    assert payloads, "TC-AUTHOR-20: the control run assembled no request payloads"
    for pin in PINS:
        value = str(getattr(author, pin))
        assert any(value in payload for payload in payloads), (
            f"TC-AUTHOR-20: {pin}={value!r} appears in no assembled request payload — a "
            "prompt edit that skips the version bump would be invisible to the request "
            "key (RISK-128's silent drift)")


def test_tc_author_20_a_bumped_pin_misses_loudly_and_never_replays_stale(
        tmp_path, make_fixture_provider, monkeypatch):
    """Bump each pin over the same recordings: the request key changes, the provider
    misses loudly, every miss carries that pin's bumped suffix, and the bumped run
    resolves strictly fewer items than the control run — never a stale replay. All three
    pins get the bump arm: a bump limb on only one pin would let the other two drift
    silently (a rubric edit without its version bump would replay the recorded success)."""
    author, recordings = _guards()

    control = _MissRecorder(make_fixture_provider(recordings))
    control_result = _af01_draft(author, recordings, control, tmp_path / "control")
    assert control_result.outcomes and control.misses == [], (
        "TC-AUTHOR-20: the control run must replay the corpus cleanly before the bump "
        "arms mean anything")

    for pin in PINS:
        bumped = f"{getattr(author, pin)}-bumped"
        monkeypatch.setattr(author, pin, bumped)
        bumped_recorder = _MissRecorder(make_fixture_provider(recordings))
        bumped_result = _af01_draft(author, recordings, bumped_recorder,
                                    tmp_path / f"bumped-{pin}")

        assert bumped_recorder.misses, (
            f"TC-AUTHOR-20: bumping {pin} changed no request key — the stale recording "
            f"replayed (RISK-128's silent drift)")
        for prompt, _ref, _message in bumped_recorder.misses:
            assert bumped in _payload_text(prompt), (
                f"TC-AUTHOR-20: a miss whose payload does not carry {pin}'s bumped "
                f"suffix is a miss for another reason")
        assert bumped_result.resolved < control_result.resolved, (
            f"TC-AUTHOR-20: the {pin}-bumped run must not serve the recorded success "
            f"for the affected step — a loud miss, never a stale replay (FR-AUTHOR-20)")
        monkeypatch.undo()  # the next pin's arm runs against the un-bumped constants