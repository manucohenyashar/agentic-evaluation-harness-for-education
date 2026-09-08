"""Run-shaped fixtures for the `M-ORCH` cases (`TS-22`, issue #63): a real store, a real
Tier P package with criteria, a seeded cohort with submissions, and a resolved `RunConfig`
— the four things every enumeration, resume and re-run case stands on.

**Why direct Tier C/P seeding here.** `M-INGEST` and `M-SETUP` are not under test in these
cases; the ledger is. Standing up a full ingest pass or a Stage A chain per example would
make each case's failure mode name a module it does not exercise. The rows written here are
exactly the rows those modules' shipped writers produce (the `cohort`/`submission` DDL and
`PackageCatalog.add_criterion`), so the ledger reads real-shaped state — which is what a
rung-2/3 case owes the oracle. The writes bypass the producers' APIs deliberately and the
bypass is **disclosed at each call site** by this docstring; no production module may do this
(`CT-ORCH-17`'s single-writership clause binds `M-ORCH`'s peers, and this support file is
test scaffolding, not a peer).
"""

from __future__ import annotations

from typing import Any, Sequence

from aeh.conf import CohortRef, resolve_run_config
from aeh.pkg import PackageCatalog
from aeh.store import open_store
from tests.support.conf_builders import (
    EDGE_JUDGE,
    EDGE_JUDGE_2,
    EDGE_JUDGE_3,
    EDGE_PANEL_3,
    SYNTHETIC_COHORT,
    edge_cfg,
)

#: The cohort every fixture here seeds, and the one the resolved config names — the two
#: must agree or `create_run`'s FK refuses the run row.
ORCH_COHORT_ID = "c-2026-7B-orch"

#: A reference stamp for the `package` row, matching the shape `in_memory_catalog` writes.
_PACKAGE_STAMP = "2026-01-01T00:00:00+00:00"


def seed_cohort(store: Any, submissions: Sequence[str], cohort_id: str | None = None) -> str:
    """Create `ORCH_COHORT_ID` (or `cohort_id`) with one submission row per name given.

    `submission` is `(submission_id, cohort_id, student_ref)` — the full shipped column
    set at the point `M-ORCH` reads it. `ingest_status` arrives with the ingest migration
    and defaults per its own DDL; cases that need specific statuses set them explicitly.
    """
    cohort_id = cohort_id or ORCH_COHORT_ID
    handle = store.cohort(cohort_id)
    with handle.transaction() as tx:
        tx.execute(
            "INSERT INTO cohort (cohort_id, consent_class, created_at) "
            "VALUES (:c, 'synthetic', :created)",
            c=cohort_id,
            created=_PACKAGE_STAMP,
        )
        for submission_id in submissions:
            tx.execute(
                "INSERT INTO submission (submission_id, cohort_id, student_ref) "
                "VALUES (:s, :c, :r)",
                s=submission_id,
                c=cohort_id,
                r=f"ref-{submission_id}",
            )
    return cohort_id


def seed_package(
    store: Any,
    criteria: Sequence[dict[str, Any]],
    *,
    package_id: str = "pkg-orch",
) -> str:
    """Create a package version whose criteria are the specs given, and return its id.

    Each spec is a `PackageCatalog.add_criterion` kwargs dict minus the version:
    `{"criterion_id": "C1", "kind": "open", "scoring_model": "holistic",
      "dependencies": ("C0",)}`. Edges are written in one `set_dependencies` call after
    the criteria exist, so a spec may name a dependency added by an earlier spec in the
    same list.
    """
    handle = store.package(package_id)
    with handle.transaction() as tx:
        tx.execute(
            "INSERT INTO package (package_id, created_at) VALUES (:p, :created)",
            p=package_id,
            created=_PACKAGE_STAMP,
        )
    catalog = PackageCatalog(handle, package_id=package_id)
    version = catalog.create_version(None)
    for spec in criteria:
        kwargs = dict(spec)
        criterion_id = kwargs.pop("criterion_id")
        catalog.add_criterion(version, criterion_id, **kwargs)
    edges = [
        (before, spec["criterion_id"])
        for spec in criteria
        for before in spec.get("dependencies", ())
    ]
    if edges:
        catalog.set_dependencies(version, edges)
    return version


def orch_cfg(profile: str = "edge-local", *, panel: Any = None) -> Any:
    """A resolved `RunConfig` naming `ORCH_COHORT_ID`, over the given profile/panel.

    Defaults to the three-judge edge panel so a `holistic` criterion enumerates its full
    base depth of 3; callers pass a narrower panel when the case is about depth clamping.
    """
    if panel is None:
        panel = EDGE_PANEL_3
    return resolve_run_config(
        edge_cfg(HARNESS_PROFILE=profile, panel=panel),
        CohortRef(cohort_id=ORCH_COHORT_ID, consent_class="synthetic"),
    )


def seed_run(
    store: Any,
    *,
    submissions: Sequence[str],
    criteria: Sequence[dict[str, Any]],
    profile: str = "edge-local",
    panel: Any = None,
    package_id: str = "pkg-orch",
    cfg: Any = None,
) -> tuple[Any, str, str]:
    """The whole fixture chain: store state in, `(orchestrator, run_id, version)` out.

    The orchestrator is returned already holding the store; `run_id` names a created run
    whose row is born `pending`. Callers enumerate with `orchestrator.enumerate_units`.
    """
    from aeh.orch import Orchestrator

    cohort_id = seed_cohort(store, submissions)
    version = seed_package(store, criteria, package_id=package_id)
    resolved = cfg if cfg is not None else orch_cfg(profile, panel=panel)
    orchestrator = Orchestrator(store)
    run_id = orchestrator.create_run(cohort_id, version, resolved)
    return orchestrator, run_id, version


__all__ = [
    "EDGE_JUDGE",
    "EDGE_JUDGE_2",
    "EDGE_JUDGE_3",
    "ORCH_COHORT_ID",
    "SYNTHETIC_COHORT",
    "orch_cfg",
    "seed_cohort",
    "seed_package",
    "seed_run",
]
