"""The vision model's residency slot: which model is loaded, and waiting for it."""

from __future__ import annotations

from typing import Sequence

from .errors import IngestError


# --- the residency slot --------------------------------------------------------------------------


class ResidencySlot:
    """The VLM's model-residency slot.

    `HardwarePolicy.residency_policy` (`M-CONF`) names the roles permitted resident
    concurrently. For the `unified-small` and `discrete-gpu` profiles the transcriber
    and the judge cannot coexist in memory: the transcriber's slot is then EXCLUSIVE,
    and a judge acquiring it waits until ingestion releases it — which is the
    acceptance criterion's "ingestion completes and the model unloads before the first
    judge loads", as a primitive the orchestrator (`M-ORCH`) acquires on both sides.

    A slot whose policy admits both roles concurrently (shared-memory profiles where
    the design allows coexistence) admits them: `acquire` is then a no-op guard, and
    the slot exists so the call sites do not change when a profile tightens.

    Waiter state is observable (#222, the F11 fix): `holder`, `waiters` and
    `exclusive` read the slot's live state, and `snapshot()` returns the
    stage-detail dict the results carry — a slot reference on a result is never
    bare.
    """

    def __init__(self, *, exclusive: bool) -> None:
        self._exclusive = exclusive
        self._holder: str | None = None
        self._waiters = 0
        if exclusive:
            import threading

            self._lock = threading.Lock()
            self._released = threading.Condition(self._lock)

    @classmethod
    def for_policy(cls, policy_roles: Sequence[str], *,
                   judge_role: str = "judge",
                   transcriber_role: str = "transcriber") -> "ResidencySlot":
        """The slot the given `HardwarePolicy.residency_policy` implies: exclusive when
        the policy does not admit the judge and the transcriber concurrently."""
        roles = tuple(policy_roles)
        exclusive = not (judge_role in roles and transcriber_role in roles)
        return cls(exclusive=exclusive)

    @property
    def exclusive(self) -> bool:
        """Whether the slot admits one resident at a time."""
        return self._exclusive

    @property
    def holder(self) -> str | None:
        """The role currently holding the slot, or None — a shared slot never
        holds (its acquire is a guard, not a hold)."""
        if not self._exclusive:
            return None
        with self._lock:
            return self._holder

    @property
    def waiters(self) -> int:
        """How many threads are currently blocked in `acquire` (#222, F11) —
        the waiter state the mid-run probes were scheduling-race-blind to. A
        shared slot never blocks, so it reads 0."""
        if not self._exclusive:
            return 0
        with self._lock:
            return self._waiters

    def snapshot(self) -> dict:
        """The slot's state as a stage-detail dict (`CLAUDE.md` seam 4): no
        result carries a bare slot reference."""
        if not self._exclusive:
            return {"exclusive": False, "holder": None, "waiters": 0}
        with self._lock:
            return {"exclusive": True, "holder": self._holder,
                    "waiters": self._waiters}

    def acquire(self, role: str = "transcriber") -> None:
        if not self._exclusive:
            return
        self._lock.acquire()
        try:
            while self._holder is not None:
                self._waiters += 1
                try:
                    self._released.wait()
                finally:
                    self._waiters -= 1
            self._holder = role
        finally:
            self._lock.release()

    def release(self, role: str = "transcriber") -> None:
        if not self._exclusive:
            return
        with self._lock:
            if self._holder != role:
                raise IngestError(
                    f"releasing the residency slot for {role!r} but {self._holder!r} "
                    "holds it — the acquire/release pairs are unbalanced."
                )
            self._holder = None
            self._released.notify_all()
