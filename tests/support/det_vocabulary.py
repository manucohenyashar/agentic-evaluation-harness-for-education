"""World-shaped fixtures for the `M-DET` cases (`TS-33`, issue #88): a real store, a real
Tier P package whose mcq criteria carry declared keys, options, bands and partial-credit
policies, a seeded cohort with submissions, a real `run` row written by `M-ORCH`, and head
documents with answer regions the §7.8 kernel reads.

**Why direct Tier C/P seeding here.** `M-INGEST` is not under test in these cases; the
deterministic evaluator is. Standing up a full ingest pass per example would make each
case's failure mode name a module it does not exercise. The rows written here are exactly
the rows the shipped writers produce — `ingest.insert_document` / `ingest.insert_region`
column shapes (including `element_kind = question_id`, the convention ingest.py:3255 fixes
for question-keyed regions) and `PackageCatalog`'s own criterion/band/option/key writes —
so the ledger reads real-shaped state. The writes bypass the producers' APIs where no API
exists (`multi_select` / `partial_credit` have no pkg setter yet; the review queue has no
writer until `M-REVIEW` lands) and every such bypass is disclosed at the call site. This
support file is test scaffolding, not a peer (`CT-ORCH-17`'s single-writership clause binds
`M-ORCH`'s peers, not the suite).
"""

from __future__ import annotations

from typing import Any, Sequence

from aeh.conf import CohortRef, resolve_run_config
from aeh.orch import Orchestrator
from aeh.pkg import PackageCatalog
from aeh.store import open_store
from tests.support.conf_builders import edge_cfg
from tests.support.orch_run import seed_cohort

#: The cohort the det fixtures seed unless a case names its own.
DET_COHORT_ID = "c-2026-9A-det"

#: A reference stamp for the `package` row and the head documents' `created_at`, matching
#: the shape `orch_run.seed_package` writes.
_STAMP = "2026-01-01T00:00:00+00:00"


def seed_det_package(
    store: Any,
    criteria: Sequence[dict[str, Any]],
    *,
    package_id: str = "pkg-det",
) -> str:
    """Create a package version whose mcq criteria are the specs given; return the version.

    Each spec: `{"criterion_id": "M1", "question_id": "Q1", "options": ("A", "B", "C"),
    "key": ("B",), "multi_select": False, "partial_credit": None}` — `multi_select` /
    `partial_credit` land in the det-migration columns via a direct write, disclosed:
    the columns exist (`det_selection_policy_columns`, package migration 10) but no pkg
    API declares them yet. Bands are the deterministic two-band scale `FR-SETUP-13`
    fixes — `incorrect` at 0.0, `correct` at the criterion's max (1.0) — declared through
    `PackageCatalog` so `points_for_band` has exactly the mapping the design names.
    """
    handle = store.package(package_id)
    with handle.transaction() as tx:
        tx.execute(
            "INSERT INTO package (package_id, created_at) VALUES (:p, :created)",
            p=package_id,
            created=_STAMP,
        )
    catalog = PackageCatalog(handle, package_id=package_id)
    version = catalog.create_version(None)
    for spec in criteria:
        criterion_id = spec["criterion_id"]
        catalog.add_criterion(
            version,
            criterion_id,
            question_id=spec.get("question_id", criterion_id),
            kind="mcq",
            scoring_model="atomic",
            band_count=2,
        )
        catalog.add_band(version, criterion_id, 0, "incorrect", 0.0)
        catalog.add_band(version, criterion_id, 1, "correct", 1.0)
        options = spec.get("options", ("A", "B", "C", "D"))
        catalog.set_mcq_options(
            version, criterion_id, [(o, f"Option {o}") for o in options]
        )
        key = spec.get("key", ("B",))
        catalog.set_answer_key(version, criterion_id, key)
        multi_select = spec.get("multi_select", False)
        partial_credit = spec.get("partial_credit")
        if multi_select or partial_credit is not None:
            # Disclosed direct write: the columns ship with det's package migration,
            # their setter does not exist yet. The CHECK constraints backstop the
            # vocabulary, so a bad value here fails loudly.
            with handle.transaction() as tx:
                tx.execute(
                    "UPDATE criterion SET multi_select = :m, partial_credit = :p "
                    "WHERE package_version_id = :v AND criterion_id = :c",
                    m=1 if multi_select else 0,
                    p=partial_credit,
                    v=version,
                    c=criterion_id,
                )
    return version


def seed_det_world(
    store: Any,
    *,
    submissions: Sequence[str],
    criteria: Sequence[dict[str, Any]],
    cohort_id: str = DET_COHORT_ID,
    package_id: str = "pkg-det",
) -> tuple[str, str, str]:
    """The whole fixture chain: store in, `(run_id, version, cohort_id)` out.

    A cohort with one submission row per name, a package version with the criteria, and a
    real run row written by `M-ORCH` (`create_run` — the sanctioned run writer). Regions
    are NOT written here; a case writes exactly the answers its table needs via
    `seed_head_document` / `seed_answer_region` (or `seed_selection_answers`).
    """
    seed_cohort(store, submissions, cohort_id)
    version = seed_det_package(store, criteria, package_id=package_id)
    resolved = resolve_run_config(
        edge_cfg(), CohortRef(cohort_id=cohort_id, consent_class="synthetic")
    )
    orchestrator = Orchestrator(store)
    run_id = orchestrator.create_run(cohort_id, version, resolved)
    return run_id, version, cohort_id


def seed_head_document(
    store: Any,
    cohort_id: str,
    submission_id: str,
    *,
    document_id: str | None = None,
    created_at: str = _STAMP,
) -> str:
    """The submission's head document, in the column shape ingest's writer produces.

    Returns the document id (minted from the submission when not named). `created_at` is
    explicit because det's head query orders by it; ingest's writer stamps the same form.
    """
    document_id = document_id or f"doc-{submission_id}"
    handle = store.cohort(cohort_id)
    with handle.transaction() as tx:
        tx.execute(
            "INSERT INTO document (document_id, submission_id, content_hash, "
            "created_at) VALUES (:d, :s, :h, :created)",
            d=document_id,
            s=submission_id,
            h=f"hash-{submission_id}",
            created=created_at,
        )
    return document_id


def seed_answer_region(
    store: Any,
    cohort_id: str,
    document_id: str,
    question_id: str,
    *,
    region_id: str | None = None,
    content_state: str = "present",
    selection_state: str | None = None,
    selection: str | None = None,
    retraction: str | None = None,
    region_kind: str = "selection_mark",
    position: int = 0,
) -> str:
    """One answer region, in the column shape ingest's writer produces.

    `element_kind` carries the question id (ingest.py:3255's convention for
    question-keyed regions — the key det's head query groups by). `selection` is the
    single option id M-INGEST writes for a resolved mark (`FR-INGEST-17`: populated only
    when resolved — so a spec with a selection and no explicit state defaults to
    `resolved`, the only state under which ingest populates it); a retraction string
    strikes the region (R47's discipline).
    """
    if selection is not None and selection_state is None:
        selection_state = "resolved"
    region_id = region_id or f"reg-{document_id}-{question_id}-{position}"
    handle = store.cohort(cohort_id)
    with handle.transaction() as tx:
        tx.execute(
            "INSERT INTO document_region (region_id, document_id, page_no, "
            "element_kind, region_kind, retraction, content_state, selection_state, "
            "selection, position) VALUES (:r, :d, 1, :q, :k, :retraction, :cs, :ss, "
            ":sel, :pos)",
            r=region_id,
            d=document_id,
            q=question_id,
            k=region_kind,
            retraction=retraction,
            cs=content_state,
            ss=selection_state,
            sel=selection,
            pos=position,
        )
    return region_id


def seed_selection_answers(
    store: Any,
    cohort_id: str,
    answers: Sequence[dict[str, Any]],
    *,
    question_id: str = "Q1",
) -> None:
    """A batch of single-answer regions, one per spec — the shape most det cases need.

    Each spec: `{"submission_id": ..., "content_state": ..., "selection_state": ...,
    "selection": ...}` (the latter two optional; a spec with no `document_id` gets its
    own head document). A spec may instead carry `{"submission_id": ..., "regions": [...]}"
    to write several regions for one question (the multiple-marks case) or
    `{"submission_id": ..., "omit_document": True}` to write nothing (the absent case).
    """
    for spec in answers:
        submission_id = spec["submission_id"]
        if spec.get("omit_document"):
            continue
        document_id = seed_head_document(store, cohort_id, submission_id)
        regions = spec.get("regions") or [spec]
        for position, region in enumerate(regions):
            seed_answer_region(
                store,
                cohort_id,
                document_id,
                question_id,
                position=position,
                content_state=region.get("content_state", "present"),
                selection_state=region.get("selection_state"),
                selection=region.get("selection"),
                retraction=region.get("retraction"),
            )


def open_det_store(tmp_data_dir: Any) -> Any:
    """Open a store over the case's data dir, with every tier's migrations applied.

    Det's runtime SQL reads M-INGEST's document/region columns and M-ORCH's run table
    (det.py's registration note): a fresh data dir needs `aeh.ingest` and `aeh.orch`
    imported before the first cohort read. Importing this support module imports both
    (via the orch run writer and the package catalog above), so every case that seeds a
    world through it satisfies the registration order by construction — recorded here so
    a case that opens a bare store without seeding knows why its first read fails.
    """
    return open_store(tmp_data_dir)


__all__ = [
    "DET_COHORT_ID",
    "open_det_store",
    "seed_answer_region",
    "seed_det_package",
    "seed_det_world",
    "seed_head_document",
    "seed_selection_answers",
]
