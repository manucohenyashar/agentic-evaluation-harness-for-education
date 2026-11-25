"""TC-JUDGE-51 (#907), the property arm: CT-JUDGE-32's stored invariant over the F-DEV replay.

Traces: FR-JUDGE-42, CT-JUDGE-32. Source: `docs/design/statistical_validity_test_plan.md` §3.1,
story T10. The implementing story is #863 (PR #918), so this arm is not written ahead.

**The invariant.** For every stored verdict of the run:

- every stored span verifies against the submission's canonical document;
- `reanchored = 1` if and only if the parser relocated one of its spans.

**The replay.** F-DEV-PIPE runs from its committed recordings through `run_to_completion`. On the
unseeded replay every reply cites its words at the right offsets, so `reanchored` is 0
everywhere and the "iff" would hold vacuously. One reply is therefore seeded as in TC-AGG-34: its
first span keeps its quoted words, and its offsets are shifted by 3 bytes on the way back from
the recording. A wrapper does this; no recording is written. The oracle then reads:

- exactly one verdict has `reanchored = 1`, and it is the seeded unit's;
- that verdict's span is stored at the words' true offsets, not at the shifted ones;
- every other verdict has `reanchored = 0`.

**"Verifies", per the design delta.** A relocated span whose quote is pseudonymized evidence is
stored with the pseudonym's text at the real name's offsets. Plain `verify_span` is False for
it (#863, pinned in TC-JUDGE-48…50's docstring). Each stored span is therefore accepted when
`verify_span` holds, or when M-JUDGE's own pseudonymized check holds for that submission's roster
name and ref, and nothing else. This is a departure from the plan's literal "`verify_span(doc,
span)` is true on every stored span", and the PR discloses it.

Isolation: rung 3. The composed pipeline over a real store, with every model answer a committed
recording keyed on its request.

Markers: `integration`.
"""

from __future__ import annotations

import dataclasses
import json
from typing import Any

import pytest

from aeh.integ import verify_span
from aeh.judge.assembly import _canonical_document_bytes
from aeh.judge.replies import _verifies_as_pseudonymized
from tests.support import pipe_world

pytestmark = pytest.mark.integration

#: How far the seeded span's offsets are moved off its words.
SHIFT = 3


class _RelocateOneCitation:
    """Shifts the offsets of the first cited span in the first citing judge reply, and remembers
    which request it answered (the unit's criterion and submission text)."""

    def __init__(self, inner: Any) -> None:
        self._inner = inner
        self.seeded: dict[str, Any] | None = None
        self.criterion_field: str | None = None

    def complete(self, prompt: Any, model_ref: Any, params: Any) -> Any:
        completion = self._inner.complete(prompt, model_ref, params)
        if self.seeded is not None or getattr(model_ref, "role", None) != "judge":
            return completion
        reply = json.loads(completion.text)
        spans = reply.get("cited_spans")
        if not spans or not spans[0].get("text"):
            return completion
        original = dict(spans[0])
        spans[0] = {**original, "start": original["start"] + SHIFT,
                    "end": original["end"] + SHIFT}
        self.seeded = original
        self.criterion_field = dict(prompt.fields)["criterion"]
        return dataclasses.replace(completion, text=json.dumps(reply))

    def __getattr__(self, name: str) -> Any:
        return getattr(self._inner, name)


def _verdicts(world: Any) -> list[dict[str, Any]]:
    return [dict(row) for row in world.store.cohort(pipe_world.PIPE_COHORT_ID).query(
        "SELECT v.work_id, v.cited_spans, v.reanchored, w.submission_id, w.criterion_id "
        "FROM verdict v JOIN work_unit w ON w.work_id = v.work_id WHERE w.run_id = :r",
        r=world.run_id)]


def _identities(world: Any) -> dict[str, tuple[str, str]]:
    """submission id -> (the roster name, the pseudonym), from the cohort's own rows."""
    rows = world.store.cohort(pipe_world.PIPE_COHORT_ID).query(
        "SELECT s.submission_id, r.full_name, s.student_ref FROM submission s "
        "JOIN roster r ON r.student_ref = s.student_ref")
    return {str(r["submission_id"]): (str(r["full_name"]), str(r["student_ref"])) for r in rows}


def test_tc_judge_51_every_stored_span_verifies_and_reanchored_iff_relocated(
        tmp_path, monkeypatch) -> None:
    monkeypatch.delenv("HARNESS_PROFILE", raising=False)
    world = pipe_world.replay_world(tmp_path / "data", monkeypatch=monkeypatch)
    world.build_run()
    world.start_run()
    wrapper = _RelocateOneCitation(world.provider)
    world.provider = wrapper
    try:
        result = pipe_world.drive_composed(world)
        assert result.status == "complete", (result.status, result.pause_reason)
        assert wrapper.seeded is not None, "fixture: no citing judge reply was seeded"
        verdicts = _verdicts(world)
        identities = _identities(world)
        documents = {submission_id: _canonical_document_bytes(world.store, submission_id)
                     for submission_id in {v["submission_id"] for v in verdicts}}
    finally:
        world.store.close()

    assert len(verdicts) >= 26, f"the replay stored {len(verdicts)} verdicts"
    assert all(raw for raw in documents.values()), "a submission's canonical document is missing"

    unverified = []
    stored_spans = 0
    for verdict in verdicts:
        raw = documents[verdict["submission_id"]]
        name, ref = identities[verdict["submission_id"]]
        for span in json.loads(verdict["cited_spans"] or "[]"):
            stored_spans += 1
            if not (verify_span(raw, span) or _verifies_as_pseudonymized(raw, span, name, ref)):
                unverified.append((verdict["criterion_id"], span))
    assert stored_spans > 0, "no verdict stored a span: the property ran over nothing"
    assert unverified == [], f"stored spans that do not verify: {unverified}"

    # reanchored = 1 iff the parser relocated a span: only the seeded verdict.
    relocated = [v for v in verdicts if int(v["reanchored"]) == 1]
    assert {int(v["reanchored"]) for v in verdicts} <= {0, 1}
    assert len(relocated) == 1, (
        f"{len(relocated)} verdicts read reanchored = 1; exactly the seeded one was relocated")
    (hit,) = relocated
    assert f"criterion_id: {hit['criterion_id']}\n" in wrapper.criterion_field + "\n", (
        "the re-anchored verdict is not the seeded unit's criterion")
    spans = json.loads(hit["cited_spans"])
    assert any((s["start"], s["end"], s["text"]) == (
        wrapper.seeded["start"], wrapper.seeded["end"], wrapper.seeded["text"]) for s in spans), (
        f"the relocated span was not stored at its words' offsets: {spans} vs {wrapper.seeded}")
