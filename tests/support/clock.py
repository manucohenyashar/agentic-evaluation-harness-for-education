"""The injected clock.

Test plan §4.2 injects a `Clock` for lease expiry, the review window, the commit interval
and backoff. §4.6 is blunt about why: *"No test in this plan may call `sleep` as a
synchronization mechanism."*

`FrozenClock` separates wall clock from monotonic on purpose. `FR-STORE-11` requires lease
expiry to derive from a monotonic counter persisted alongside wall-clock time, "so that a
clock moving backwards on resume cannot make an expired lease appear live" — and the only
way to test that is a clock whose wall time can move backwards while monotonic does not.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Protocol, runtime_checkable

EPOCH = datetime(2026, 1, 1, 0, 0, 0, tzinfo=timezone.utc)


@runtime_checkable
class Clock(Protocol):
    """The seam every time-dependent module takes as a constructor argument."""

    def now(self) -> datetime: ...

    def monotonic(self) -> float: ...


class FrozenClock:
    """A clock that moves only when a test moves it."""

    def __init__(self, start: datetime = EPOCH, monotonic_start: float = 0.0) -> None:
        self._now = start
        self._monotonic = monotonic_start

    def now(self) -> datetime:
        return self._now

    def monotonic(self) -> float:
        return self._monotonic

    def advance(self, seconds: float) -> None:
        """Move both clocks forward. The normal case."""
        if seconds < 0:
            raise ValueError(
                "advance() moves time forward; use set_wall_clock() to simulate a wall "
                "clock that jumped backwards (FR-STORE-11)"
            )
        self._now += timedelta(seconds=seconds)
        self._monotonic += seconds

    def set_wall_clock(self, when: datetime) -> None:
        """Move wall time only, in either direction. Monotonic is untouched.

        This is the resume-after-clock-skew scenario: NTP corrects the host clock backwards
        while the monotonic counter keeps counting. An expired lease must still compare as
        expired.
        """
        self._now = when
