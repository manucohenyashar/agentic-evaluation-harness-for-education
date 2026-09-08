"""`CT-INGEST-18` — parallel pages and submissions; the residency slot
(`TC-INGEST-C18`).

Case of test plan §6.11.5; issue #49 (TS-62). Green by design — the slot and
the per-page call shape are shipped (#36..#41).

The clause: ~4 pages per submission, one VLM call per page (~1,400 calls per
350-student cohort — the arithmetic M-ORCH's batch multiplies; the per-page
unit is what is assertable here). Ingestion is fully parallel across pages and
submissions with **no ordering constraint** — asserted as a differential:
the same submissions ingested in a different order produce identical outputs.
On the `discrete-gpu` and `unified-small` profiles the VLM occupies its own
residency slot and **unloads before the first judge loads** — asserted as an
event-order property, since an overlap silently costs the overnight window.

The event-order oracle runs on a shared timeline: the provider's calls and the
residency's grants append to ONE list, so "no call outside the slot" and
"release after the last call" are order facts, not two reconciled logs. The
judge half is the slot's own exclusivity, probed with a gate so the timing is
deterministic: the ingest is held mid-call while a judge thread waits on the
slot, and the judge's grant is recorded only after the transcriber's release.

Consumer halves deferred with disclosure: the 350-student batch and the
orchestrated overlap are M-ORCH's (#59..#66); `TC-INGEST-02`'s cohort-scale
threshold is its case. What the producer holds here is the per-page call unit
and the slot primitive the batch would run on.
"""
from __future__ import annotations

import threading

import pytest

from aeh.ingest import Ingestor, ResidencySlot
from aeh.prov import SamplingParams
from tests.contract.ingest._doubles import (
    COHORT,
    Contract,
    RecordingResidency,
    ScriptedProvider,
    ThroughSanitizer,
    answer_text,
    student_answer,
)

pytestmark = pytest.mark.contract


class TimelineProvider(ScriptedProvider):
    """The scripted model, appending every completed call to the SHARED
    timeline — after the call, so the timeline's order is completion order."""

    def __init__(self, timeline: list) -> None:
        super().__init__()
        self._timeline = timeline

    def complete(self, prompt, model_ref, params):
        completion = super().complete(prompt, model_ref, params)
        self._timeline.append(("call", self.calls[-1]))
        return completion


class TimelineResidency:
    """The exclusive slot, appending to the SHARED timeline at GRANT time — the
    event only appears once `acquire` returned, so the timeline's order is the
    order the slot was actually held."""

    def __init__(self, timeline: list) -> None:
        self._slot = ResidencySlot(exclusive=True)
        self._timeline = timeline

    def acquire(self, role: str = "transcriber") -> None:
        self._slot.acquire(role)
        self._timeline.append(("acquire", role))

    def release(self, role: str = "transcriber") -> None:
        self._slot.release(role)
        self._timeline.append(("release", role))

    def holds(self, role: str = "transcriber") -> bool:
        return self._slot._holder == role  # noqa: SLF001 -- test-side probe


class GatedProvider(ScriptedProvider):
    """The scripted model with a deterministic mid-ingest hold: the FIRST call
    opens `first_call`; every later call blocks on `gate` — the ingest is
    provably inside its second model call, slot held, while the probe runs."""

    def __init__(self, first_call: threading.Event,
                 gate: threading.Event) -> None:
        super().__init__()
        self._first_call = first_call
        self._gate = gate

    def complete(self, prompt, model_ref, params):
        completion = super().complete(prompt, model_ref, params)
        if not self._first_call.is_set():
            self._first_call.set()
        else:
            self._gate.wait(timeout=10)
        return completion


class GrantOrderedResidency(RecordingResidency):
    """A `RecordingResidency` whose acquire records at GRANT time — the event
    list is the order the slot was actually held, which the plain recorder's
    append-then-block does not give. The release records BEFORE releasing:
    `slot.release` wakes a waiting acquirer whose own append could otherwise
    race this thread's record into the list first."""

    def acquire(self, role: str = "transcriber") -> None:
        self._slot.acquire(role)
        self.events.append(("acquire", role))

    def release(self, role: str = "transcriber") -> None:
        self.events.append(("release", role))
        self._slot.release(role)


def test_tc_ingest_c18_one_call_per_page_between_acquire_and_release(
        tmp_data_dir):
    """`TC-INGEST-C18` (per-page unit + event order) — a three-page submission
    makes EXACTLY three model calls, one per page, and the shared timeline
    reads `acquire, call, call, call, release`: every call strictly inside the
    slot, released after the last — the VLM is never called unloaded and never
    left loaded after the work."""
    timeline: list = []
    fx = Contract(tmp_data_dir, "c18-timeline", residency=False,
                  provider=TimelineProvider(timeline))
    fx.ingestor = Ingestor(
        fx.handle, fx.blobs, fx.provider, fx.model,
        SamplingParams(temperature=0.0), fx.rasterizer,
        residency=TimelineResidency(timeline), sanitizer=ThroughSanitizer())
    fx.add_roster("gus")
    blobs = [fx.put(f"c18 page {index}".encode()) for index in (1, 2, 3)]
    for index, blob in enumerate(blobs, start=1):
        fx.script(blob, {1: student_answer("gus", answer_text(
            "Q1", f"the page {index} answer"))})
    report = fx.ingestor.ingest_submission(
        blobs, cohort_id=COHORT, package_version="v0", order_hint=blobs)
    assert report.ingest_status == "ok", (
        f"TC-INGEST-C18: the three-page submission did not complete: "
        f"{report.ingest_status} / {report.gates}."
    )
    kinds = [kind for kind, _ in timeline]
    assert kinds == ["acquire"] + ["call"] * 3 + ["release"], (
        f"TC-INGEST-C18: the timeline reads {timeline} — the slot and the "
        "calls are not one acquire, the per-page calls, one release."
    )
    called = [payload for kind, payload in timeline if kind == "call"]
    assert len(set(called)) == 3, (
        f"TC-INGEST-C18: the calls are {called} — a page called twice or a "
        "batched call: not one VLM call per page."
    )
    fx.close()


def test_tc_ingest_c18_the_judge_loads_only_after_the_transcriber_unloads(
        tmp_data_dir):
    """`TC-INGEST-C18` (residency, judge half) — while the ingest holds the
    slot (proved: the ingest is blocked INSIDE its second model call by the
    gate), a judge thread's acquire is NOT granted; the moment the ingest
    releases — after its last call — the waiting judge is granted. The
    grant-ordered events read `acquire(transcriber) … release(transcriber),
    acquire(judge)`: the unload precedes the judge's load, as an order fact."""
    first_call, gate = threading.Event(), threading.Event()
    fx = Contract(tmp_data_dir, "c18-judge", provider=GatedProvider(first_call,
                                                                    gate))
    fx.residency = GrantOrderedResidency()
    fx.ingestor = Ingestor(
        fx.handle, fx.blobs, fx.provider, fx.model,
        SamplingParams(temperature=0.0), fx.rasterizer,
        residency=fx.residency, sanitizer=ThroughSanitizer())
    fx.add_roster("gus")
    one, two = fx.put(b"c18 judge p1"), fx.put(b"c18 judge p2")
    fx.script(one, {1: student_answer("gus", answer_text("Q1", "first"))})
    fx.script(two, {1: student_answer("gus", answer_text("Q1", "second"))})
    result: dict = {}

    def ingest():
        result["report"] = fx.ingestor.ingest_submission(
            [one, two], cohort_id=COHORT, package_version="v0",
            order_hint=[one, two])

    worker = threading.Thread(target=ingest)
    worker.start()
    try:
        assert first_call.wait(timeout=10), (
            "TC-INGEST-C18: the ingest never reached its first model call."
        )
        assert fx.residency.holds("transcriber"), (
            "TC-INGEST-C18: the transcriber does not hold the slot during its "
            "own call — the VLM runs unloaded."
        )
        judge_granted = threading.Event()

        def judge():
            fx.residency.acquire("judge")
            judge_granted.set()

        waiter = threading.Thread(target=judge)
        waiter.start()
        # The ingest is blocked inside its second call (the gate), the slot is
        # provably held — the judge must still be waiting.
        assert not judge_granted.wait(timeout=0.3), (
            "TC-INGEST-C18: a judge acquired the slot while the transcriber "
            "held it — the profiles' exclusivity is gone."
        )
        gate.set()
        worker.join(timeout=10)
        assert not worker.is_alive(), (
            "TC-INGEST-C18: the ingest never finished after the gate opened."
        )
        assert judge_granted.wait(timeout=5), (
            "TC-INGEST-C18: the waiting judge was never granted the slot "
            "after the transcriber released it."
        )
        events = fx.residency.events
        assert events.index(("release", "transcriber")) \
            < events.index(("acquire", "judge")), (
            f"TC-INGEST-C18: the grant order is {events} — the judge loaded "
            "before the transcriber unloaded."
        )
        assert result["report"].ingest_status == "ok", (
            f"TC-INGEST-C18: the gated ingest did not complete: "
            f"{result['report'].ingest_status}."
        )
    finally:
        gate.set()
        worker.join(timeout=5)
    fx.close()


def test_tc_ingest_c18_the_policy_slot_is_exclusive_without_coexistence(
        tmp_data_dir):
    """`TC-INGEST-C18` (policy half) — `ResidencySlot.for_policy` is the
    profile switch: a policy that admits both roles concurrently admits them
    (acquire is a no-op guard, the call sites do not change), and a policy that
    does not — `discrete-gpu`/`unified-small` — makes a second role WAIT until
    the holder releases."""
    from tests.contract.ingest._doubles import RecordingResidency
    shared = ResidencySlot.for_policy(("transcriber", "judge"))
    exclusive = ResidencySlot.for_policy(("transcriber",))
    # Shared: both roles hold concurrently, no waiting.
    shared.acquire("transcriber")
    shared.acquire("judge")  # returns: coexistence admitted
    shared.release("judge")
    shared.release("transcriber")
    # Exclusive: a second role waits for the release.
    exclusive.acquire("transcriber")
    admitted = threading.Event()

    def second_role():
        exclusive.acquire("judge")
        admitted.set()

    waiter = threading.Thread(target=second_role)
    waiter.start()
    try:
        assert not admitted.wait(timeout=0.3), (
            "TC-INGEST-C18: the exclusive policy slot admitted a second role "
            "while the first held it."
        )
    finally:
        exclusive.release("transcriber")
        waiter.join(timeout=5)
    assert admitted.is_set(), (
        "TC-INGEST-C18: the waiter was never admitted after the release."
    )


def test_tc_ingest_c18_a_shuffled_work_order_produces_identical_output(
        tmp_data_dir):
    """`TC-INGEST-C18` (the differential) — the same three submissions ingested
    in two different orders produce identical outputs: per submission, the same
    gate tuple, status, transcriber build, document content hash and region
    structure. No call-order constraint exists — a scheduler may run the units
    in any order, and no output can depend on the order it chose."""
    bodies = {"a": "the first paper's answer",
              "b": "the second paper's answer",
              "c": "the third paper's answer"}

    def build(fx: Contract) -> dict[str, str]:
        fx.add_roster("gus")
        blobs = {name: fx.put(f"c18 diff {name}".encode())
                 for name in ("a", "b", "c")}
        for name, blob in blobs.items():
            fx.script(blob, {1: student_answer(
                "gus", answer_text("Q1", bodies[name]))})
        return blobs

    first, second = Contract(tmp_data_dir, "c18-order-a"), \
        Contract(tmp_data_dir, "c18-order-b")
    fa, fb = build(first), build(second)
    reports = {}
    for fixture, order in ((first, ["a", "b", "c"]), (second, ["c", "b", "a"])):
        for name in order:
            reports[(id(fixture), name)] = fixture.ingestor.ingest_submission(
                [fa[name] if fixture is first else fb[name]],
                cohort_id=COHORT, package_version="v0",
                filenames={fa[name] if fixture is first else fb[name]:
                           f"{name}.pdf"})

    def shape(fixture: Contract, name: str):
        report = reports[(id(fixture), name)]
        blob = fa[name] if fixture is first else fb[name]
        document = fixture.documents(
            "submission_id = :s", s=report.submission_id)[0]
        regions = sorted(
            (row["page_no"], row["element_kind"], row["region_kind"],
             row["content_state"], row["selection_state"], row["content"])
            for row in fixture.regions(document["document_id"]))
        return (report.ingest_status, tuple(sorted(report.gates.items())),
                report.v4_signals, document["content_hash"],
                document["transcriber_ref"], regions)

    for name in ("a", "b", "c"):
        one, two = shape(first, name), shape(second, name)
        assert one == two, (
            f"TC-INGEST-C18: submission {name!r} ingested under two work "
            f"orders differs:\n  order [a,b,c]: {one}\n  order [c,b,a]: {two}"
        )
    # And the call count is the same in both: one per page, order-free.
    assert len(first.provider.calls) == len(second.provider.calls) == 3, (
        f"TC-INGEST-C18: the two orders made {len(first.provider.calls)} vs "
        f"{len(second.provider.calls)} calls — the work order changed the "
        "work."
    )
    first.close()
    second.close()
