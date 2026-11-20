"""Recording one administration into the validation record, and the per-population aggregate."""

from __future__ import annotations

from typing import TYPE_CHECKING

import json
import sqlite3
import time
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping, Sequence

from .settings import NO_NEW_VALIDATION_EVIDENCE, _ORIGIN_TO_EVIDENCE
from .admissibility import _is_admissible, _row_mapping, _StoredLabel, _system_side
from .agreement import _band_ordinals, _corrected_statistics
from .schema import STATS_STATEMENTS
from .engines import agreement_by_engine, decision_engine_noninferior, engine_partition
from .records import ValidationAggregate, ValidationUpdate
from .comparisons import _paired_sides, _refuse_foreign_cohort, _require_str_or_none
from .administration import (
    NO_ENGINE_CONTEXT,
    STORED_JSON_KEYS,
    EngineContext,
    criterion_figures,
    cumulative_figures,
)

if TYPE_CHECKING:
    from .service import ValidationStats


# --- the validation record (#118, FR-STATS-10..14, CT-STATS-05/06/09/14/19) -------------------------
#
# `promote` is the record's writer: the one member of this module that holds a
# write to the durable tier. The clause `CT-STATS-15` enforces is about the
# *route* — the record's own claim (the administration's unclaimed label and
# audit rows stamped with the administration's cohort id, in Tier D) is this
# module's write, while the package tier's row goes **through**
# `aeh.pkg.record_promotion`, whose frames make the write `M-PKG`'s (the
# indirection the write audit asserts). What the record may never write — a
# score, a grade, a narrative, package content — is enforced statically and
# behaviourally (`TC-STATS-C15`), which is why every statement the writer uses
# is declared in ``STATS_STATEMENTS`` above rather than assembled at a call
# site.


def _label_evidence_key(label: Any) -> str:
    """Which evidence class a label counts as for the weighted signal (FR-STATS-14): its `origin`
    when the weights name it, else its type (a blind label is blind evidence, anything else
    acceptance). Every label gets a class, so none is silently dropped."""
    origin = getattr(label, "origin", None)
    if origin in _ORIGIN_TO_EVIDENCE:
        return _ORIGIN_TO_EVIDENCE[origin]
    return "blind" if getattr(label, "label_type", "") == "blind" else "acceptance"


def _label_pair_agrees(label: Any) -> bool | None:
    """Whether a label's two bands agree, or None when it has only one side; the signal drops
    exactly the labels the agreement figure drops."""
    system = _system_side(label)
    teacher = getattr(label, "teacher_band", None)
    if system is None or teacher is None:
        return None
    return system == teacher


def _per_criterion_kappas(
    population: Sequence[Any], band_counts: Mapping[str, int]
) -> dict[str, float | None]:
    """Each criterion's chance-corrected coefficient over one population, using the same helpers as
    `agreement`, so the record's figure is the same figure. A criterion with fewer than two pairs
    gives None (CT-STATS-16)."""
    criteria = sorted({
        (getattr(label, "criterion_id", "") or "") for label in population
    })
    figures: dict[str, float | None] = {}
    for criterion in criteria:
        subset = [
            label
            for label in population
            if (getattr(label, "criterion_id", "") or "") == criterion
        ]
        paired = _paired_sides(subset)
        if len(paired) < 2:
            figures[criterion] = None
            continue
        ordinals, inferred_band_count = _band_ordinals(paired)
        band_count = max(band_counts.get(criterion) or 0, inferred_band_count)
        kappa, _qwk, _alpha, _po, _pe = _corrected_statistics(
            ordinals, band_count
        )
        figures[criterion] = kappa
    return figures


def _weakest_entry(
    kappas: Mapping[str, float | None],
) -> Mapping[str, Any]:
    """The weakest criterion in a per-criterion kappa map: the lowest computable value, ties broken
    by criterion id. When none is computable, it says so (`kappa=None`) instead of showing a
    number."""
    computable = {
        criterion: kappa for criterion, kappa in kappas.items() if kappa is not None
    }
    if computable:
        criterion = min(sorted(computable), key=lambda name: computable[name])
        return {"criterion_id": criterion, "kappa": computable[criterion]}
    if kappas:
        return {"criterion_id": sorted(kappas)[0], "kappa": None}
    return {"criterion_id": None, "kappa": None}


def _label_scope(label: Any) -> str | None:
    """The population scope a label carries, from whichever attribute holds it. Stored labels have
    no scope column yet, so they read as None and the aggregate reports the population-wide figure
    for scopes it cannot split."""
    scope = getattr(label, "population_scope_id", None)
    if scope is None:
        scope = getattr(label, "scope", None)
    return scope


def _label_run(label: Any) -> str | None:
    """The run a label was written for, from its attribute or its stored row."""
    run_id = getattr(label, "run_id", None)
    if run_id is None:
        run_id = (getattr(label, "_row", {}) or {}).get("run_id")
    return str(run_id) if run_id else None


def _administration_population(
    population: Sequence[Any], run_id: str | None, absence_reason: str | None
) -> tuple[list[Any], list[Any]]:
    """`(population, admissible)` for the administration a promote records.

    A named run narrows the cohort's labels to that run's (one administration per run's draw);
    a skip collects no evidence, so its admissible population is empty whatever else the
    cohort holds (FR-STATS-33: a skip writes `blind_count = 0`)."""
    if run_id is not None:
        population = [label for label in population if _label_run(label) == run_id]
    admissible = [] if absence_reason == "skipped" else [
        label for label in population if _is_admissible(label)]
    return list(population), admissible


def _require_absence_reason(absence_reason: str | None, unmarked_count: int) -> None:
    if absence_reason not in (None, "skipped", "none_marked"):
        raise ValueError(
            f"promote got absence_reason={absence_reason!r}; an administration's record "
            "names 'skipped', 'none_marked' or no absence (FR-STATS-33)"
        )
    if isinstance(unmarked_count, bool) or not isinstance(unmarked_count, int) or (
            unmarked_count < 0):
        raise ValueError(
            f"promote got unmarked_count={unmarked_count!r}; it counts drawn seats left "
            "unmarked, a whole number of at least 0"
        )


def promote(
    self: "ValidationStats",
    cohort_id: str | None = None,
    *,
    package_version: str | None = None,
    run_id: str | None = None,
    absence_reason: str | None = None,
    unmarked_count: int = 0,
) -> ValidationUpdate:
    """Record one administration (FR-STATS-10, CT-STATS-05, CT-STATS-06): claim the
    administration's unclaimed labels for the named cohort, count what was claimed, compute the
    per-criterion figures (FR-STATS-32), and write the record's durable rows through
    `aeh.pkg.record_promotion`, so the write happens in M-PKG on M-STATS's behalf (CT-STATS-15).

    #879: one record per administration (FR-STATS-33) — when the (package version, cohort)
    record already exists this call claims nothing, writes nothing and returns the stored record
    (`already_recorded=True`). ``run_id`` narrows the record to one run's labels; the draw's
    ``absence_reason`` (`skipped`, `none_marked`) and ``unmarked_count`` are written on the
    record (migration P2). The anomaly baseline is written from the administration's final
    scores (FR-STATS-34). M-PIPE's `promote_administration` is the production caller, on draw
    close only (FR-PIPE-21).

    More detail: `docs/code-notes/stats.md`, section `promotion.py: promote`.
    """
    _require_str_or_none("promote", cohort_id=cohort_id, package_version=package_version,
                         run_id=run_id)
    _require_absence_reason(absence_reason, unmarked_count)
    _refuse_foreign_cohort(self, cohort_id, "promote")

    data_dir = self._data_dir
    if data_dir is None:
        return self._record_in_memory(cohort_id, package_version, run_id=run_id,
                                      absence_reason=absence_reason,
                                      unmarked_count=unmarked_count)

    # The durable record is keyed on its administration; a promote of neither
    # a passed nor a bound cohort would count the unclaimed labels into a row
    # keyed ("", "") and leave them unclaimed — a later administration's
    # promote would then claim and count the same labels again. Refuse rather
    # than write a record that makes the next one lie (rung 0 has no store, so
    # the in-memory shape above has nothing to double-count and stays).
    if cohort_id is None and self._cohort_id is None:
        raise ValueError(
            "promote needs an administration to record: pass cohort_id=, or "
            "open_stats(cohort_id=...). An unkeyed record row would leave the "
            "labels unclaimed for the next administration to re-count."
        )
    administration_key = cohort_id or self._cohort_id or ""

    # --- rung 2: the durable claim --------------------------------------------------------------
    database_path = Path(data_dir) / "durable.sqlite"
    connection = sqlite3.connect(str(database_path))
    connection.row_factory = sqlite3.Row
    try:
        # The audit rows are read unclaimed and never stamped (`audit_record`
        # is append-only — #103's trigger — and no writer sets the column at
        # insert), so the read spans every administration's rows. That is
        # exactly why sourcing refuses a multi-version world (see
        # `_record_sourcing`): nothing in this read names *this*
        # administration's revision except agreement or an explicit
        # ``package_version=``.
        audits = [
            _row_mapping(row)
            for row in connection.execute(STATS_STATEMENTS["select_unclaimed_audits"])
        ]
        # A named run sources the record from its own audit rows, so its figures and baseline
        # are filed under THAT run's backend and panel build, not whichever unclaimed row
        # another run left first (FR-STATS-32's scope).
        run_audits = [row for row in audits if str(row.get("run_id")) == run_id]
        package_version_id, backend_profile, panel_build_ref = _record_sourcing(
            package_version, run_audits or audits
        )
        # FR-STATS-33: one record per administration. Checked before the claim, so a
        # second call claims no label twice and writes no second row.
        existing = connection.execute(
            STATS_STATEMENTS["select_promotion_record"],
            {"package_version_id": package_version_id, "cohort_id": administration_key},
        ).fetchone()
        if existing is not None:
            stored_figures = [
                _row_mapping(row) for row in connection.execute(
                    STATS_STATEMENTS["select_administration_criterion_stats"],
                    {"package_version_id": package_version_id,
                     "cohort_id": administration_key})
            ]
            return _stored_update(_row_mapping(existing), stored_figures)
        if cohort_id is not None:
            # Labels only: `audit_record` is append-only (#103's trigger,
            # `FR-DET-10`/`TC-GRADE-23`), so the audit rows' cohort dimension
            # rode their insert and the record reads them unclaimed rather
            # than stamping them — an update here would raise.
            connection.execute(
                STATS_STATEMENTS["claim_labels"], {"cohort_id": cohort_id}
            )
        connection.commit()
        if self._cohort_id is not None:
            rows = connection.execute(
                STATS_STATEMENTS["select_labels"], {"cohort_id": self._cohort_id}
            ).fetchall()
        else:
            rows = connection.execute(
                STATS_STATEMENTS["select_labels_all"]
            ).fetchall()
        self._labels = [_StoredLabel(_row_mapping(row)) for row in rows]
    finally:
        connection.close()

    population, admissible = _administration_population(
        self._scoped_population(cohort_id), run_id, absence_reason)
    recomputation_started = time.perf_counter()
    if cohort_id is None:
        claimed_cohorts = {
            getattr(label, "cohort_id", None)
            for label in population
            if getattr(label, "cohort_id", None) is not None
        }
        cohorts_used = len(claimed_cohorts)
    else:
        # The same arithmetic rung 0 reports: an administration that collected
        # nothing is still recorded (the row is the disclosure), but the
        # record speaks for zero cohorts' evidence.
        cohorts_used = 1 if population else 0
    blind_count = len(admissible)
    operational_count = len(population) - blind_count

    # The declared scale and scoring model of each criterion (Tier P), so QWK's three-band rule
    # reads the DECLARED band count and each figure carries its model (FR-STATS-03/32). What the
    # constructor was given wins; the package fills the rest.
    scales = _pkg_scales(data_dir, package_version_id)
    band_counts = {criterion: len(scale["bands"]) for criterion, scale in scales.items()}
    band_counts.update(self._band_counts)
    scoring_models = {criterion: scale["scoring_model"] for criterion, scale in scales.items()}
    scoring_models.update(self._scoring_models)
    band_names = {criterion: scale["bands"] for criterion, scale in scales.items()}

    # This administration's runs: the one named, or the runs its labels were written for.
    administration_runs = ({run_id} if run_id is not None else
                           {run for run in map(_label_run, population) if run})
    context, final_bands, context_close = _administration_context(
        data_dir, administration_key, administration_runs)
    try:
        figures = criterion_figures(admissible, band_counts=band_counts,
                                    band_names=band_names, scoring_models=scoring_models,
                                    context=context)
    finally:
        context_close()
    per_criterion = {criterion: figure["kappa"] for criterion, figure in figures.items()}
    if len(per_criterion) == 1:
        agreement_kappa = next(iter(per_criterion.values()))
    else:
        agreement_kappa = None
    weakest = {administration_key: _weakest_entry(per_criterion)}

    # The run's own key parts (#454 reopened): `_record_sourcing` hands back the audit row's
    # whole profile summary and panel config, which are provenance, not key values. A record a
    # run's reader must find (FR-PKG-08's six-part key) is filed under the summary's
    # `backend_profile` and `panel_build_ref`, the values `run_handle` reports — and so are the
    # per-criterion figures (#879), so FR-STATS-32's backend and panel-build scope is the run's.
    key_backend, key_panel = _run_key_parts(backend_profile, panel_build_ref)
    connection = sqlite3.connect(str(database_path))
    connection.row_factory = sqlite3.Row
    try:
        # FR-STATS-35 (#881): the version's record so far, pooled with this administration and
        # stored beside its own figures, so the package record reads a stored figure.
        earlier = [_row_mapping(row) for row in connection.execute(
            STATS_STATEMENTS["select_earlier_criterion_stats"],
            {"package_version_id": package_version_id, "cohort_id": administration_key})]
        cumulative = cumulative_figures(figures, earlier, backend_profile=key_backend,
                                        panel_build_ref=key_panel)
        for criterion, figure in figures.items():
            figure["cumulative"] = cumulative[criterion]
        for criterion, figure in sorted(figures.items()):
            connection.execute(
                STATS_STATEMENTS["record_criterion_stats"],
                {
                    "package_version_id": package_version_id,
                    "criterion_id": criterion,
                    "backend_profile": key_backend,
                    "panel_build_ref": key_panel,
                    "n": figure["n"],
                    "cohort_id": administration_key,
                    "scoring_model": figure["scoring_model"],
                    "matched": figure["matched"],
                    "kappa": figure["kappa"],
                    "qwk": figure["qwk"],
                    "reason": figure["reason"],
                    "figures": json.dumps(
                        {key: figure[key] for key in STORED_JSON_KEYS}, sort_keys=True),
                },
            )
        connection.commit()
    finally:
        connection.close()

    flags = tuple(self.surface_proxies().surface_proxy_flags)
    message = NO_NEW_VALIDATION_EVIDENCE if blind_count == 0 else ""
    # The counter is the honest measurement of the recomputation this record
    # just did — scope, sourcing, per-criterion figures, weakest entries,
    # proxy flags — read by `observability_counters` as
    # ``statistics_recomputation_duration``.
    self._last_recomputation_seconds = time.perf_counter() - recomputation_started

    from aeh import pkg as _pkg

    # FR-STATS-34 (#879; #373 before it, `FR-AGG-08`): the baseline distribution per judged
    # criterion, from the administration's FINAL SCORES — the distribution a later cell's
    # band is an anomaly against. (#373 counted the blind labels' teacher bands; FR-STATS-34
    # names the final scores, which every graded cell has and a skipped administration still
    # holds.) Band NAMES go over, not ordinals: the scale those names sit on is Tier P's
    # (`record_validation_baseline` maps them).
    #
    # The outcome per criterion rides the RESULT. Every way this write can decline is an
    # ordinary event — the commonest being a later administration of a published package,
    # whose recorded baseline `FR-PKG-04` freezes — so a promote that said nothing about the
    # baseline would be the seam-4 trap in miniature.
    baseline_outcomes: dict[str, str] = {}
    for criterion in sorted(final_bands):
        histogram = final_bands[criterion]
        if not histogram:
            baseline_outcomes[criterion] = _pkg.BASELINE_NO_HISTOGRAM
            continue
        written = _pkg.record_validation_baseline(
            data_dir,
            package_version_id=package_version_id,
            criterion_id=criterion,
            band_histogram=histogram,
            backend_profile=key_backend,
            panel_build_ref=key_panel,
        )
        # The reason travels whether or not the write landed. This module logs nothing
        # (it has no logger, by long standing), so the returned record IS the disclosure:
        # `ValidationUpdate.baseline_outcomes` below.
        baseline_outcomes[criterion] = written.reason

    # FR-STATS-29 (#454): when the run froze a decision engine (its persisted profile summary
    # names one), the engine non-inferiority verdict per criterion is written through
    # FR-PKG-23. An engine-off run writes nothing, so the column stays NULL (NFR-SYS-14).
    # Only THIS administration's runs decide: the unclaimed-audit read spans every
    # administration, and an older engine-on run must not make an engine-off promote write a
    # verdict (or overwrite a recorded 'false') (#454 review). The figure itself is computed
    # for every administration and rides `criterion_figures` (FR-STATS-32).
    noninferiority_outcomes: dict[str, str] = {}
    if any('"decision_engine"' in str(row.get("profile_summary") or "")
           for row in audits if str(row.get("run_id")) in administration_runs):
        noninferiority_outcomes = _record_noninferiority_verdicts(
            data_dir, administration_key, package_version_id, per_criterion, admissible,
            key_backend, key_panel)

    _pkg.record_promotion(
        data_dir,
        package_version_id=package_version_id,
        cohort_id=administration_key,
        cohorts_used=cohorts_used,
        operational_count=operational_count,
        blind_count=blind_count,
        n=blind_count,
        agreement_kappa=agreement_kappa,
        weakest_per_population=json.dumps(weakest, sort_keys=True),
        surface_proxy_flags=json.dumps(list(flags)),
        message=message,
        absence_reason=absence_reason,
        unmarked_count=unmarked_count,
    )
    return ValidationUpdate(
        cohort_id=administration_key,
        package_version_id=package_version_id,
        cohorts_used=cohorts_used,
        operational_count=operational_count,
        blind_count=blind_count,
        n=blind_count,
        agreement_kappa=agreement_kappa,
        weakest_per_population=weakest,
        surface_proxy_flags=flags,
        message=message,
        baseline_outcomes=baseline_outcomes,
        noninferiority_outcomes=noninferiority_outcomes,
        criterion_figures=figures,
        absence_reason=absence_reason,
        unmarked_count=unmarked_count,
    )


def administration_record(store: Any, *, package_version_id: str,
                          cohort_id: str) -> ValidationUpdate | None:
    """One administration's stored record (FR-STATS-33), as the `ValidationUpdate` its promote
    returned, or None when the administration was never promoted. A read of stored figures
    only: it never recomputes a figure (NFR-STATS-07)."""
    handle = store.durable()
    rows = handle.query(STATS_STATEMENTS["select_promotion_record"],
                        package_version_id=package_version_id, cohort_id=cohort_id)
    if not rows:
        return None
    figures = handle.query(STATS_STATEMENTS["select_administration_criterion_stats"],
                           package_version_id=package_version_id, cohort_id=cohort_id)
    return _stored_update(_row_mapping(rows[0]), [_row_mapping(row) for row in figures])


def _pkg_scales(data_dir: Any, package_version_id: str) -> dict[str, dict[str, Any]]:
    from aeh import pkg as _pkg

    return _pkg.criterion_scales(data_dir, package_version_id)


def _administration_context(
    data_dir: Any, cohort_id: str, runs: set[str],
) -> tuple[EngineContext, dict[str, dict[str, int]], Callable[[], None]]:
    """The cohort reads one administration's promote needs, from one store open: each labelled
    cell's engine partition and accepted gate confidence (FR-STATS-26/27), and the runs' final
    band histograms per judged criterion (FR-STATS-34). Returns the context, the histograms and
    the closer for the store the context reads through. No cohort file → no context and no
    histograms."""
    from aeh.store import open_store

    if not cohort_id or not Path(data_dir, "cohorts", f"{cohort_id}.sqlite").exists():
        return NO_ENGINE_CONTEXT, {}, lambda: None
    store = open_store(data_dir)
    try:
        handle = store.cohort(cohort_id)
        histograms: dict[str, dict[str, int]] = {}
        for run in sorted(runs):
            for row in handle.query(STATS_STATEMENTS["select_run_final_bands"], run_id=run):
                band = row["band"]
                if band is None or str(band) == "":
                    continue
                counts = histograms.setdefault(str(row["criterion_id"]), {})
                counts[str(band)] = counts.get(str(band), 0) + 1
    except Exception:
        store.close()
        raise

    def _cell(label: Any) -> tuple[str, str, str] | None:
        row = getattr(label, "_row", {}) or {}
        run, student_ref = row.get("run_id"), row.get("student_ref")
        if not run or not student_ref:
            return None
        return str(run), str(student_ref), _criterion_of_label(label)

    def partition_of(label: Any) -> str | None:
        cell = _cell(label)
        return None if cell is None else engine_partition(handle, *cell)

    def confidence_of(label: Any) -> tuple[float, float] | None:
        cell = _cell(label)
        if cell is None:
            return None
        submissions = handle.query(STATS_STATEMENTS["select_submission_for_ref"],
                                   student_ref=cell[1])
        if not submissions:
            return None
        rows = handle.query(STATS_STATEMENTS["select_cell_accepted_prescreen"], run_id=cell[0],
                            submission_id=submissions[0]["submission_id"],
                            criterion_id=cell[2])
        if not rows:
            return None
        threshold = rows[0]["threshold"]
        return float(rows[0]["band_confidence"]), float(
            threshold if threshold is not None else 0.80)

    return EngineContext(partition_of, confidence_of), histograms, store.close


def _criterion_of_label(label: Any) -> str:
    return str(getattr(label, "criterion_id", "") or "")


def _stored_update(record: Mapping[str, Any],
                   criterion_rows: Sequence[Mapping[str, Any]]) -> ValidationUpdate:
    """The `ValidationUpdate` an already-written administration record stands for (FR-STATS-33):
    the stored counters and figures, read back, with `already_recorded=True`."""
    figures: dict[str, dict[str, Any]] = {}
    for row in criterion_rows:
        try:
            extra = json.loads(row.get("figures") or "{}")
        except (TypeError, ValueError):
            extra = {}
        figures[str(row["criterion_id"])] = {
            "criterion_id": str(row["criterion_id"]),
            "scoring_model": row.get("scoring_model") or "",
            "n": int(row.get("n") or 0),
            "matched": row.get("matched"),
            "kappa": row.get("kappa"),
            "qwk": row.get("qwk"),
            "reason": row.get("reason"),
            **(extra if isinstance(extra, dict) else {}),
        }

    def _json(raw: Any, default: Any) -> Any:
        try:
            return json.loads(raw) if raw else default
        except (TypeError, ValueError):
            return default

    return ValidationUpdate(
        cohort_id=str(record["cohort_id"]),
        package_version_id=str(record["package_version_id"]),
        cohorts_used=int(record.get("cohorts_used") or 0),
        operational_count=int(record.get("operational_count") or 0),
        blind_count=int(record.get("blind_count") or 0),
        n=int(record.get("n") or 0),
        agreement_kappa=record.get("agreement_kappa"),
        weakest_per_population=_json(record.get("weakest_per_population"), {}),
        surface_proxy_flags=tuple(_json(record.get("surface_proxy_flags"), [])),
        message=str(record.get("message") or ""),
        criterion_figures=figures,
        absence_reason=record.get("absence_reason"),
        unmarked_count=int(record.get("unmarked_count") or 0),
        already_recorded=True,
    )


def _record_noninferiority_verdicts(data_dir: Any, cohort_id: str, package_version_id: str,
                                    criteria: Iterable[str], admissible: Sequence[Any],
                                    backend_profile: str, panel_build_ref: str) -> dict[str, str]:
    """Write each criterion's non-inferiority verdict (NFR-STATS-06) onto its validation record
    (FR-STATS-29, FR-PKG-23), from the per-engine agreement over the administration's admissible
    labels, with each label's partition read from the cohort's own verdicts. M-STATS never switches
    engines (CT-CONF-14)."""
    from aeh import pkg as _pkg
    from aeh.store import open_store

    if not cohort_id or not Path(data_dir, "cohorts", f"{cohort_id}.sqlite").exists():
        return {criterion: "not recorded: the administration has no cohort file to read "
                           "engine partitions from" for criterion in criteria}
    outcomes: dict[str, str] = {}
    store = open_store(data_dir)
    try:
        handle = store.cohort(cohort_id)

        def partition_of(label: Any) -> str | None:
            row = getattr(label, "_row", {}) or {}
            run_id, student_ref = row.get("run_id"), row.get("student_ref")
            if not run_id or not student_ref:
                return None
            return engine_partition(handle, str(run_id), str(student_ref),
                                    str(getattr(label, "criterion_id", "") or ""))

        for criterion in sorted(criteria):
            labels = [label for label in admissible
                      if (getattr(label, "criterion_id", "") or "") == criterion]
            verdict = decision_engine_noninferior(agreement_by_engine(labels, partition_of))
            written = _pkg.record_noninferiority(
                data_dir, package_version_id=package_version_id, criterion_id=criterion,
                verdict=verdict, backend_profile=backend_profile,
                panel_build_ref=panel_build_ref)
            outcomes[criterion] = (f"recorded {verdict}" if written.recorded
                                   else f"not recorded: {written.reason}")
    finally:
        store.close()
    return outcomes


def _run_key_parts(profile_summary: str, panel_config: str) -> tuple[str, str]:
    """`(backend_profile, panel_build_ref)` from a stored profile summary.

    The summary is the JSON `M-CONF`'s `ProfileSummary` persists; it carries both key parts
    by name. A summary that is not that JSON (the literal ``unrecorded``, a bare profile
    name from an older audit row) is passed through as the backend with the panel config as
    given, which is the reading this module had before."""
    try:
        summary = json.loads(profile_summary)
    except (TypeError, ValueError):
        return profile_summary, panel_config
    if not isinstance(summary, dict) or not summary.get("backend_profile"):
        return profile_summary, panel_config
    return str(summary["backend_profile"]), str(summary.get("panel_build_ref") or "")


def _record_sourcing(
    package_version: str | None, audits: Sequence[Mapping[str, Any]]
) -> tuple[str, str, str]:
    """Where the record's per-criterion rows get their provenance: the caller's `package_version=`
    first, then the audit rows' version when they all agree, otherwise the literal `unrecorded`.
    `profile_summary` and `panel_config` come from the same rows.

    Audits spanning **more than one** version are a refusal, not a vote: the
    unclaimed-audit read cannot tell which administration collected under
    which revision (the append-only trail carries no per-row cohort), so a
    majority across administrations would attribute this record — and its
    ``criterion_stats`` rows — to a revision the labels were not collected
    under. The caller declares the version, or the record is not written."""
    version = package_version
    if version is None:
        versions = sorted({
            str(row.get("package_version_id"))
            for row in audits
            if row.get("package_version_id")
        })
        if len(versions) > 1:
            raise ValueError(
                "promote cannot source a record across package versions "
                f"{versions}: the audit trail carries no per-row cohort, so "
                "no reading of it names THIS administration's revision. Pass "
                "package_version= explicitly to record one."
            )
        if versions:
            version = versions[0]
    profile = next(
        (str(row.get("profile_summary")) for row in audits if row.get("profile_summary")),
        None,
    )
    panel = next(
        (str(row.get("panel_config")) for row in audits if row.get("panel_config")),
        None,
    )
    return (
        version if version else "unrecorded",
        profile if profile else "unrecorded",
        panel if panel else "unrecorded",
    )


def aggregate(
    self: "ValidationStats", across: str | None = None
) -> ValidationAggregate:
    """The per-population aggregate (CT-STATS-04): the weakest criterion for each declared
    population scope, and nothing that spans scopes.

    The refusal is the other half of the clause: ``across=`` accepts a value
    precisely so a spanning request can be refused by name, and any value is
    refused — population, backend, assignment type, a scoring model — because
    `CT-STATS-04`'s prohibition is on the *combination*, not on a particular
    spelling of it (`FR-STATS-13`'s exposure lives in
    ``weakest_per_population``, beside the figures, not instead of them).

    Each declared scope maps to the weakest criterion among its admissible
    labels — lowest computable κ, criterion id breaking ties in sorted order.
    The labels the in-memory constructor holds carry no scope of their own, so
    a scope the labels cannot be attributed to reports the population-wide
    weakest rather than an invented split: the declared scopes are what this
    installation knows, and the aggregate says what the data supports, which
    is the disclosure this value exists to carry. A scope with no admissible
    labels of its own reads the same disclosure."""
    if across is not None:
        raise ValueError(
            f"aggregate() was asked for across={across!r}; the contract keeps "
            "population, backend, assignment type and scoring model apart "
            "(CT-STATS-04), and a value spanning them is the claim this module "
            "exists to keep unrepresentable. The per-population reading lives "
            "in weakest_per_population; the per-criterion figures live in "
            "agreement()."
        )
    scopes = list(self._population_scopes) or [""]
    admissible = self.admissible_labels()
    weakest: dict[str, Mapping[str, Any]] = {}
    for scope in scopes:
        scoped = [
            label for label in admissible if _label_scope(label) == scope
        ]
        if not scoped:
            scoped = admissible
        kappas = _per_criterion_kappas(scoped, self._band_counts)
        weakest[scope] = _weakest_entry(kappas)
    return ValidationAggregate(
        population_scopes=tuple(scopes), weakest_per_population=weakest
    )


def _scoped_population(
    self: "ValidationStats", cohort_id: str | None
) -> list[Any]:
    """The population one administration's record speaks for.

    Three cases, each honest about what it knows (`CT-STATS-05`'s
    administration is the caller): a named cohort narrows to the labels that
    carry it — the rows the durable claim stamped; a cohort named over an
    in-memory population that carries no cohort facts at all is the held
    population, disclosed as the shape it is (a rung-0 population has no
    administration keying to narrow by, and pretending otherwise would make
    every rung-0 record an empty one); no cohort named reads every label the
    instance holds."""
    if cohort_id is None:
        return list(self._labels)
    if not any(
        getattr(label, "cohort_id", None) is not None for label in self._labels
    ):
        return list(self._labels)
    return [
        label
        for label in self._labels
        if getattr(label, "cohort_id", None) == cohort_id
    ]


def _record_in_memory(
    self: "ValidationStats",
    cohort_id: str | None,
    package_version: str | None,
    *,
    run_id: str | None = None,
    absence_reason: str | None = None,
    unmarked_count: int = 0,
) -> ValidationUpdate:
    """`promote` for an in-memory instance (from `build_stats`, which has no data directory): the
    same counters, per-criterion figures, weakest entry and no-evidence message as the durable
    path, with nothing written (CT-STATS-15). With no store there are no cells, so every engine
    figure reads `insufficient_data`."""
    population, admissible = _administration_population(
        self._scoped_population(cohort_id), run_id, absence_reason)
    recomputation_started = time.perf_counter()
    administration_key = (
        cohort_id or self._cohort_id or self._administration_id or ""
    )
    cohorts_used = 1 if population else 0
    blind_count = len(admissible)
    operational_count = len(population) - blind_count
    figures = criterion_figures(admissible, band_counts=self._band_counts, band_names={},
                                scoring_models=self._scoring_models)
    per_criterion = {criterion: figure["kappa"] for criterion, figure in figures.items()}
    agreement_kappa = (
        next(iter(per_criterion.values())) if len(per_criterion) == 1 else None
    )
    weakest = {administration_key: _weakest_entry(per_criterion)}
    flags = tuple(self.surface_proxies().surface_proxy_flags)
    message = NO_NEW_VALIDATION_EVIDENCE if blind_count == 0 else ""
    self._last_recomputation_seconds = (
        time.perf_counter() - recomputation_started
    )
    return ValidationUpdate(
        cohort_id=administration_key,
        package_version_id=package_version,
        cohorts_used=cohorts_used,
        operational_count=operational_count,
        blind_count=blind_count,
        n=blind_count,
        agreement_kappa=agreement_kappa,
        weakest_per_population=weakest,
        surface_proxy_flags=flags,
        message=message,
        criterion_figures=figures,
        absence_reason=absence_reason,
        unmarked_count=unmarked_count,
    )
