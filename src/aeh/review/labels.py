"""The process-level label store, and the durable collection route for labels."""

from __future__ import annotations

import itertools
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .errors import ReviewError
from .schema import REVIEW_STATEMENTS
from .records import BlindSampleSkipReport, LabelRecord


# --- the module-level label store (FR-REVIEW-09, #110) ------------------------------------------------
#
# A process-level store for labels written *outside* a service session — the
# route the C07/C08 vocabulary exercises (`record_label`/`labels_for`). It is
# deliberately separate from `ReviewService`'s own bookkeeping: a service's
# labels are per-session (its ids, its runs, its optional durable rows), and a
# shared store would leak labels between tests and sessions. The durable
# persistence is the service's, over a real store (`CT-STORE-01`: the spy
# stores expose no transactional execute).

_LABEL_TYPES: tuple[str, ...] = ("accept", "edit", "override", "blind")


_LABEL_STORE: dict[str, list[LabelRecord]] = {}


_LABEL_STORE_COUNTER = itertools.count(1)


def record_label(
    *,
    run_id: str | None = None,
    score_id: str | None = None,
    label_type: str | None = None,
    teacher_band: str | None = None,
    system_band: str | None = None,
    saw_system_output: int | None = None,
    routing: str = "queued",
    origin: str = "escalation",
    evaluation_mode: str = "judged",
    review_seconds: float = 0,
    criterion_id: str = "",
    actor: str = "teacher",
    timestamp: str | None = None,
    review_queue_action: str | None = None,
    data_dir: Path | str | None = None,
    label: Any = None,
    cohort_id: str | None = None,
) -> str:
    """Write one label to the process-level label store and return its id (FR-REVIEW-09), for
    labels that do not come from a queue action.

    More detail: `docs/code-notes/review.md`, section `labels.py: record_label`.
    """
    if label is not None:
        if run_id is not None or score_id is not None or label_type is not None:
            raise TypeError(
                "record_label() mixes its two routes: the durable collection route "
                "takes data_dir=, label= and optional cohort_id=, while the "
                "in-memory route takes run_id=, score_id= and label_type= — a call "
                "carrying both is ambiguous about where the label should land"
            )
        if data_dir is None:
            raise TypeError(
                "record_label(label=...) is the durable collection route and needs "
                "data_dir= — the directory the label store lives in"
            )
        return _write_collected_label(
            label=label, data_dir=data_dir, cohort_id=cohort_id
        )
    if data_dir is not None or cohort_id is not None:
        raise TypeError(
            "record_label() got data_dir=/cohort_id= without label= — those name "
            "the durable collection route, which writes a collected label object"
        )
    if run_id is None or score_id is None or label_type is None:
        raise TypeError(
            "record_label() needs either label= with data_dir= (the durable "
            "collection route) or run_id=, score_id= and label_type= (the "
            "in-memory route); this call carries neither"
        )
    if label_type not in _LABEL_TYPES:
        raise ValueError(f"{label_type!r} is not a label type; one of {_LABEL_TYPES}")
    if saw_system_output is None:
        saw_system_output = 0 if label_type == "blind" else 1
    elif saw_system_output not in (0, 1):
        raise ValueError(
            f"saw_system_output is a visibility flag, not a number: it is 1 (the "
            f"system output was visible) or 0 (the label was written blind), got "
            f"{saw_system_output!r} — any other value is indistinguishable from a "
            "real one at query time"
        )
    label = LabelRecord(
        label_id=f"stored-{next(_LABEL_STORE_COUNTER):04d}",
        label_type=label_type,
        saw_system_output=int(saw_system_output),
        routing=routing,
        origin=origin,
        evaluation_mode=evaluation_mode,
        review_seconds=review_seconds,
        system_band=system_band,
        teacher_band=teacher_band,
        actor=actor,
        timestamp=timestamp or datetime.now(timezone.utc).isoformat(),
        score_id=score_id,
        criterion_id=criterion_id,
        review_queue_action=review_queue_action,
        new_points=None,
    )
    _LABEL_STORE.setdefault(run_id, []).append(label)
    return label.label_id


def labels_for(*, run_id: str) -> tuple[LabelRecord, ...]:
    """Every label stored in the process-level store for one run, in write order, as a tuple
    (CT-REVIEW-07)."""
    return tuple(_LABEL_STORE.get(run_id, ()))


#: One open store per data directory, for the collection route. Opening a
#: store is the expensive half of a write (the migration-chain check, the WAL
#: recovery) and a collection loop writes hundreds of labels into one, so the
#: handle is cached per resolved directory for the life of the process — the
#: same shape `ReviewService` holds its own store with, at module scope
#: because the collection route has no service instance to hold it.
_COLLECTED_STORES: dict[str, Any] = {}


def _collection_store(data_dir: Path | str) -> Any:
    """The open store behind the label collection route, cached per data directory.

    The tier migration chains are concatenated at import time by the modules
    that own the schema they add (CLAUDE.md): the first open in a process must
    not happen with the chain short. These ten plus *this module* — which owns
    Durable's label-store columns — make the complete chain; importing
    aeh.review from inside aeh.review is a no-op, so the ten it does not own
    are imported here, mirroring ``open_review``'s block."""
    import aeh.agg  # noqa: F401
    import aeh.det  # noqa: F401
    import aeh.extract  # noqa: F401
    import aeh.grade  # noqa: F401
    import aeh.ingest  # noqa: F401
    import aeh.integ  # noqa: F401
    import aeh.judge  # noqa: F401
    import aeh.orch  # noqa: F401
    import aeh.pkg  # noqa: F401
    import aeh.synth  # noqa: F401

    from aeh.store import open_store

    key = str(Path(data_dir))
    store = _COLLECTED_STORES.get(key)
    if store is None:
        store = open_store(data_dir)
        _COLLECTED_STORES[key] = store
    return store


def _write_collected_label(
    *, label: Any, data_dir: Path | str, cohort_id: str | None
) -> str:
    """Store one collected label in Tier D through `upsert_label` and return its id.

    The column mapping reads whatever the label carries and refuses what the
    table cannot: a label with no id is a programming error, and a label with
    no teacher band — or no evaluation mode, which the table's check admits
    as 'judged' or 'deterministic' only — is refused the way ``_persist_label``
    refuses the band, named at the route rather than dying as a raw
    constraint error. Columns the
    collection route has no opinion on (the score link, the queue action, the
    derived points) are written NULL rather than defaulted, so a reader can
    tell "not collected" from "collected as empty". The store is left open —
    ``_collection_store`` caches it, and closing it per label would reopen the
    migration chain on the next call."""
    label_id = getattr(label, "label_id", None)
    if not label_id:
        raise TypeError(
            f"record_label(label={label!r}) carries no label_id — the durable "
            "row's identity is the label's own id, and a collection without one "
            "cannot be read back"
        )
    teacher_band = getattr(label, "teacher_band", None)
    if teacher_band is None:
        raise ReviewError(
            f"label {label_id!r} records no band; Tier D's label table carries "
            "a band for every label, so a collection without one is refused"
        )
    evaluation_mode = getattr(label, "evaluation_mode", None)
    if not evaluation_mode:
        raise ReviewError(
            f"label {label_id!r} records no evaluation mode; the label table "
            "admits 'judged' or 'deterministic' only (`CT-DET-06`), so a "
            "collection without one is refused rather than dying as a raw "
            "constraint error"
        )
    store = _collection_store(data_dir)
    handle = store.durable()
    # Hoisted: the same value the `system_band` column below is written from, needed a
    # second time for `FR-REVIEW-21`'s `agreed`.
    system_band = getattr(label, "system_band", None) or getattr(label, "band", None)
    with handle.transaction() as tx:
        tx.execute(
            REVIEW_STATEMENTS["upsert_label"],
            label_id=label_id,
            run_id="",
            # The collected label carries no student identity either (#108's
            # mapping records the same absence): the submission reference is
            # what the row can honestly carry in Phase 1.
            student_ref=getattr(label, "submission_id", None) or "",
            criterion_id=getattr(label, "criterion_id", None) or "",
            label_type=getattr(label, "label_type", None) or "",
            band=teacher_band,
            evaluation_mode=getattr(label, "evaluation_mode", None) or "",
            # #356 (`FR-STATS-22`, GAP-18): a label whose source shape never carried the
            # flag is written as 1 — the honest worst case the Durable 6 migration's own
            # default states ("they count as operational, not as validity evidence they
            # never were"). Writing 0 would mint blind evidence nobody recorded, durably,
            # where no later consumer-side reading can take it back.
            saw_system_output=(
                1 if getattr(label, "saw_system_output", None) is None
                else int(bool(label.saw_system_output))
            ),
            routing=getattr(label, "routing", None) or "queued",
            origin=getattr(label, "origin", None) or "direct",
            review_seconds=getattr(label, "review_seconds", None) or 0,
            system_band=system_band,
            teacher_band=teacher_band,
            actor=getattr(label, "actor", None) or "",
            timestamp=getattr(label, "timestamp", None),
            score_id=None,
            review_queue_action=None,
            new_points=None,
            cohort_id=cohort_id,
            # `FR-REVIEW-21`'s columns on the collection route. This route carries no run
            # (`run_id=""` above), so the package-derived FIGURES are honestly unknown
            # rather than defaulted — a 0 `band_distance` here would read as "the teacher
            # agreed" about a judgement this route cannot see the band scale for. The
            # package LINKAGE itself is not unknown: #525's defect 3, the label names the
            # version it was collected against and the row records it, because a history
            # that pools unversioned labels counts one package's reviews for another that
            # shares only a criterion name (`FR-STATS-24`, `TC-REVIEW-37`).
            package_version_id=getattr(label, "package_version_id", None) or None,
            assignment_type=None,
            band_distance=None,
            system_points=None,
            teacher_points=None,
            # `agreed` needs no scale: two band ids are equal or they are not. It is the
            # figure `FR-STATS-24` counts, so a collected label still carries a history.
            agreed=(
                None if not (system_band and teacher_band)
                else (1 if str(system_band) == str(teacher_band) else 0)
            ),
            panel_config=None,
            recorded_at=getattr(label, "timestamp", None),
            # FR-REVIEW-23: this route carries no run, so the backend is whatever the
            # collected label itself records, and NULL (not attributable) otherwise.
            backend_profile=getattr(label, "backend_profile", None) or None,
        )
    return str(label_id)


def blind_sample_skipped(service: Any, run_id: str = "run-1") -> BlindSampleSkipReport:
    """Whether a service's run skipped the blind sample, the consequence in words, and
    `current_figure = None` always (FR-REVIEW-13, CT-REVIEW-10). Like `record_label` and
    `labels_for`, the report is read about a service from outside it."""
    return service.skip_report(run_id)
