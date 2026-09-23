"""The world every `M-PIPE` composition case in this directory runs against, and the one
disclosure they all inherit.

**F-DEV-PIPE does not exist.** The gap-fix test plan (§4.4) specifies every M-PIPE case against
`F-DEV-PIPE` — "3 submissions × 1 question × 3 criteria (2 judged, 1 MCQ-deterministic)", drawn
from F-DEV's generator with recorded responses for every extraction, panel call and narrative.
No such corpus is committed: `fixtures/F-DEV` is 8 submissions against the full 15-criterion
`PKG-REF`, and building F-DEV-PIPE is `harness/corpora/build.py` work — a generated artifact
with a manifest, a content hash and two gate tests pinning it — not test code. It is a finding
about the plan, recorded here and in #377's PR rather than worked around quietly.

**What these cases use instead**, stated so nobody mistakes it for the specified world:
`tests.support.e2e_world.SynthWorld` at `n_submissions=3` — the assembled system over the
synthesized cohort (real store, real catalog, real orchestrator, real workers, real gate, the
model boundary the only double) over the **15-criterion** reference package. It is the closest
real rung-3 world the repo has, and it is *wider* than F-DEV-PIPE, never narrower.

**The consequence, and how it is handled.** F-DEV-PIPE's numeric preconditions do not transfer:
`TC-PIPE-01`'s `units = 6, done = 6` counts 3 submissions × 2 judged criteria, and this world has
more. Every such figure is therefore derived **from the run's own ledger** rather than
hard-coded — `done == len(units)`, `quarantined == 0`, and the trace's figures equal the
ledger's. That keeps the oracle exact: it still fails when a unit is left undone or when the
trace disagrees with the rows. A hard-coded 6 here would fail for the wrong reason and teach a
reader nothing.

The *structural* oracles — stage order, one entry per stage, the payload-before-done invariant,
exact spy call counts, the hook sequence, the atomicity arm, `fallback=True`, the pause reason
string — do not depend on the criterion count and transfer unchanged. They are where these cases
earn their keep.

**A factory, not a fixture that builds.** Every case probes `aeh.pipeline` with `require(...)`
before it builds anything, so a missing `M-PIPE` is a legible failure in milliseconds rather than
a setup error after a world build (the reason `make_fixture_provider` is shaped this way too — a
fixture that raises produces a pytest *error*, and an error asserts nothing about the
requirement).
"""

from __future__ import annotations

from typing import Any

import pytest

from tests.support.e2e_world import SynthWorld

#: F-DEV-PIPE's submission count, which this world *can* honour even though its criterion
#: count it cannot. `QUARANTINE_INDICES` starts at 10, so at 3 submissions none quarantine —
#: which is `TC-PIPE-06` (a)'s "all submissions are complete" precondition, for free.
PIPE_SUBMISSIONS = 3


@pytest.fixture
def make_pipe_world(tmp_data_dir, tmp_path, monkeypatch):
    """Build the composition world on demand, after the caller has probed `M-PIPE`.

    `monkeypatch` is passed through deliberately: `SynthWorld.__init__` writes `os.environ`
    directly when it is None, and with `pytest-randomly` shuffling that is a cross-test leak.
    """
    built: list[Any] = []

    def _make(*, started: bool = True, **kwargs: Any) -> Any:
        world = SynthWorld(
            tmp_data_dir,
            tmp_path / "fixtures",
            n_submissions=PIPE_SUBMISSIONS,
            monkeypatch=monkeypatch,
            **kwargs,
        )
        world.build_run()
        if started:
            world.start_run()
        built.append(world)
        return world

    yield _make

    for world in built:
        world.store.close()


def extract_units(world: Any) -> tuple[Any, ...]:
    """The run's `extract` units, read off the ledger — the denominator every count-bearing
    assertion in this directory is expressed against, rather than F-DEV-PIPE's figure of 6."""
    from aeh.orch import STAGE_EXTRACT

    return tuple(
        row for row in world.orchestrator.enumerate_units(world.run_id)
        if getattr(row, "stage", None) == STAGE_EXTRACT
    )


def judged_cells(world: Any) -> tuple[tuple[str, str], ...]:
    """Every `(submission_id, criterion_id)` cell the panel judges in this run."""
    return tuple(
        (sid, cid) for sid in world.admitted_ids() for cid in world.open_ids
    )
