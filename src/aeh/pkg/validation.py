"""The validation record's durable writes: promotions, non-inferiority, baselines."""

from __future__ import annotations

import json
import math
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from .statements import PKG_STATEMENTS, _SELECT_PROMOTION_RECORD


def promotion_record(store: Any, *, package_version_id: str, cohort_id: str) -> dict[str, Any] | None:
    """The validation record `record_promotion` wrote for one administration (one package version,
    one cohort), or None (FR-CONSOLE-24). Read-only."""
    rows = store.durable().query(_SELECT_PROMOTION_RECORD, package_version_id=package_version_id,
                                 cohort_id=cohort_id)
    return dict(rows[0]) if rows else None


def record_promotion(
    data_dir: Path | str,
    *,
    package_version_id: str,
    cohort_id: str,
    cohorts_used: int,
    operational_count: int,
    blind_count: int,
    n: int,
    agreement_kappa: float | None,
    weakest_per_population: str,
    surface_proxy_flags: str,
    message: str,
    recorded_at: str | None = None,
) -> None:
    """Write the validation record's durable row (FR-STATS-10): one `package_validation` row per
    (package version, cohort) in Tier D. M-STATS's `promote` is the only intended caller; the write
    lives in M-PKG because the table belongs to this tier's schema (CT-STATS-15).

    The figures arrive as the caller computed them — counters, the nullable
    ``agreement_kappa``, the two JSON documents (``weakest_per_population``,
    ``surface_proxy_flags``) — and this function shapes nothing: it is the
    record's transport, not its second author. ``recorded_at`` defaults to
    now, in UTC, as the durable column requires."""
    if recorded_at is None:
        recorded_at = datetime.now(timezone.utc).isoformat()
    database_path = Path(data_dir) / "durable.sqlite"
    connection = sqlite3.connect(str(database_path))
    try:
        connection.execute(
            "INSERT OR REPLACE INTO package_validation "
            "(package_version_id, cohort_id, recorded_at, cohorts_used, "
            "operational_count, blind_count, n, agreement_kappa, "
            "weakest_per_population, surface_proxy_flags, message) VALUES "
            "(:package_version_id, :cohort_id, :recorded_at, :cohorts_used, "
            ":operational_count, :blind_count, :n, :agreement_kappa, "
            ":weakest_per_population, :surface_proxy_flags, :message)",
            {
                "package_version_id": package_version_id,
                "cohort_id": cohort_id,
                "recorded_at": recorded_at,
                "cohorts_used": cohorts_used,
                "operational_count": operational_count,
                "blind_count": blind_count,
                "n": n,
                "agreement_kappa": agreement_kappa,
                "weakest_per_population": weakest_per_population,
                "surface_proxy_flags": surface_proxy_flags,
                "message": message,
            },
        )
        connection.commit()
    finally:
        connection.close()


#: The one value `record_validation_baseline` accepts for the two key parts `M-STATS` does
#: not carry. The six-part key (`FR-PKG-08`) dimensions a validation record by population and
#: scoring model; an administration's promote knows neither, and INVENTING one would file the
#: baseline under a population it was never measured on — the exact non-transfer error R30 put
#: those parts in the key to prevent. The empty string is the key's "not dimensioned here"
#: value, which `validation_for`'s `scoring_model: str = ""` default already uses.
_BASELINE_UNDIMENSIONED = ""


@dataclass(frozen=True)
class BaselineWrite:
    """What `record_validation_baseline` did, and, when it did nothing, why.

    A bare ``bool`` was the first shape and it was the wrong one. Every refusal this
    function makes is a NORMAL event on the production path (the commonest by far is a
    promote against a published package), so the caller's only signal that its baseline
    never landed would have been a `False` it had no reason to inspect. That is the
    silent-failure trap exactly: a promote reporting success on top of a record that was
    never written. `reason` is what the caller puts in its own trace.

    `recorded` is the status; `reason` is one of the `BASELINE_*` codes below and is
    always set, `BASELINE_RECORDED` included, so a log line never has to special-case
    success.
    """

    recorded: bool
    reason: str


#: `record_validation_baseline`'s outcome codes. Named constants rather than bare strings
#: so a caller can branch on one without matching prose that may be reworded.
BASELINE_RECORDED = "recorded"


BASELINE_NO_HISTOGRAM = "the histogram was empty or summed to zero"


BASELINE_NO_PACKAGES = "the data directory holds no packages"


BASELINE_NO_SUCH_VERSION = "no package in this data directory holds that version"


BASELINE_UNDECLARED_BAND = "the histogram names a band the criterion does not declare"


BASELINE_PUBLISHED = (
    "the version is published and the write was refused (FR-PKG-04): the published "
    "baseline exception (#525) appends evidence only, and never alters a recorded figure"
)


def _population_mean_and_sd(weighted: Mapping[int, int]) -> tuple[float, float]:
    """The mean and population standard deviation of a weighted histogram of ordinals.

    Population, not sample: the histogram IS the administration's judged distribution, not a
    draw from a larger one to be estimated. The baseline describes the labels that exist, so
    dividing by ``n`` rather than ``n-1`` is the honest arithmetic — and it also keeps a
    single-label administration expressible (sd 0.0) instead of a division by zero.
    """
    total = sum(weighted.values())
    mean = sum(ordinal * count for ordinal, count in weighted.items()) / total
    variance = sum(
        count * (ordinal - mean) ** 2 for ordinal, count in weighted.items()
    ) / total
    return mean, math.sqrt(variance)


#: FR-PKG-23's stored spellings of NFR-STATS-06's verdict.
NONINFERIORITY_VERDICTS: tuple[str, ...] = ("true", "false", "insufficient_data")


def record_noninferiority(
    data_dir: Path | str,
    *,
    package_version_id: str,
    criterion_id: str,
    verdict: bool | str,
    population_scope_id: str = _BASELINE_UNDIMENSIONED,
    backend_profile: str = _BASELINE_UNDIMENSIONED,
    panel_build_ref: str = _BASELINE_UNDIMENSIONED,
    scoring_model: str = _BASELINE_UNDIMENSIONED,
) -> BaselineWrite:
    """Write the decision engine's non-inferiority verdict (NFR-STATS-06) onto the criterion's
    validation record under the six-part key (FR-PKG-23). `verdict` is True, False or
    `'insufficient_data'`. Refuses, returning the reason rather than raising, when the version is
    not in this data directory or is published (its records are frozen, FR-PKG-04)."""
    # The column's CHECK is the one authority on the domain (TC-PKG-33): a value outside it
    # surfaces as the database's IntegrityError, never as a quiet refusal.
    stored = ("true" if verdict is True else "false" if verdict is False else str(verdict))
    directory = Path(data_dir) / "packages"
    if not directory.is_dir():
        return BaselineWrite(False, BASELINE_NO_PACKAGES)
    for database_path in sorted(directory.glob("*.pkg.sqlite")):
        connection = sqlite3.connect(str(database_path))
        connection.row_factory = sqlite3.Row
        try:
            try:
                present = connection.execute(
                    PKG_STATEMENTS["select_version_present"], {"v": package_version_id}
                ).fetchall()
            except sqlite3.OperationalError:
                continue
            if not present:
                continue
            parameters = {
                "v": package_version_id, "criterion_id": criterion_id,
                "population_scope_id": population_scope_id, "backend_profile": backend_profile,
                "panel_build_ref": panel_build_ref, "scoring_model": scoring_model,
                "verdict": stored,
            }
            try:
                cursor = connection.execute(
                    PKG_STATEMENTS["update_validation_noninferiority"], parameters)
                if cursor.rowcount == 0:
                    connection.execute(
                        PKG_STATEMENTS["insert_validation_noninferiority"], parameters)
                connection.commit()
            except sqlite3.IntegrityError as error:
                connection.rollback()
                if "CHECK constraint failed" in str(error):
                    raise  # a verdict outside the declared domain is a caller's error
                return BaselineWrite(False, BASELINE_PUBLISHED)
            return BaselineWrite(True, BASELINE_RECORDED)
        finally:
            connection.close()
    return BaselineWrite(False, BASELINE_NO_SUCH_VERSION)


def record_validation_baseline(
    data_dir: Path | str,
    *,
    package_version_id: str,
    criterion_id: str,
    band_histogram: Mapping[str, int],
    population_scope_id: str = _BASELINE_UNDIMENSIONED,
    backend_profile: str = _BASELINE_UNDIMENSIONED,
    panel_build_ref: str = _BASELINE_UNDIMENSIONED,
    scoring_model: str = _BASELINE_UNDIMENSIONED,
) -> BaselineWrite:
    """Write one criterion's baseline band distribution onto its `validation_record` row.

    On a **published** version the write is append-only — decision (a) of #525, the one
    sanctioned exception to FR-PKG-04's freeze, because every version a run grades against
    is published and the escalation baseline (`FR-PIPE-15`) is evidence ABOUT the version.
    The exception appends: a new baseline row may be added, and a row whose three figure
    columns are still NULL may be filled, but a recorded figure is never altered — a
    rewrite comes back refused with `BASELINE_PUBLISHED`, as does any agreement or engine
    verdict write.

    More detail: `docs/code-notes/pkg.md`, section `validation.py: record_validation_baseline`.
    """
    if not band_histogram or sum(band_histogram.values()) <= 0:
        return BaselineWrite(False, BASELINE_NO_HISTOGRAM)
    directory = Path(data_dir) / "packages"
    if not directory.is_dir():
        return BaselineWrite(False, BASELINE_NO_PACKAGES)
    for database_path in sorted(directory.glob("*.pkg.sqlite")):
        connection = sqlite3.connect(str(database_path))
        connection.row_factory = sqlite3.Row
        try:
            try:
                present = connection.execute(
                    PKG_STATEMENTS["select_version_present"], {"v": package_version_id}
                ).fetchall()
            except sqlite3.OperationalError:
                # A file matching the glob that is not a package database — no
                # `package_version` table. This loop's whole job is to find the file
                # holding the version, so a file that cannot answer the question is
                # skipped like one that answers "no". Note the narrowness: a genuine
                # schema fault in a file that IS a package still raises below, where the
                # statement it breaks names it.
                continue
            if not present:
                continue
            ordinals = {
                str(row["band"]): int(row["ordinal"])
                for row in connection.execute(
                    PKG_STATEMENTS["select_criterion_band_ordinals"],
                    {"v": package_version_id, "criterion_id": criterion_id},
                ).fetchall()
            }
            weighted: dict[int, int] = {}
            for band_name, count in band_histogram.items():
                if str(band_name) not in ordinals:
                    return BaselineWrite(False, BASELINE_UNDECLARED_BAND)
                ordinal = ordinals[str(band_name)]
                weighted[ordinal] = weighted.get(ordinal, 0) + int(count)
            mean, sd = _population_mean_and_sd(weighted)
            # Keyed by the ORDINAL, the same scale `expected_mean` is in, so the stored
            # record is self-consistent: a reader that recomputes the mean from the
            # histogram gets the stored mean back. Keys are strings because JSON has no
            # integer keys.
            histogram = json.dumps(
                {str(ordinal): count for ordinal, count in sorted(weighted.items())},
                sort_keys=True,
            )
            parameters = {
                "v": package_version_id,
                "criterion_id": criterion_id,
                "population_scope_id": population_scope_id,
                "backend_profile": backend_profile,
                "panel_build_ref": panel_build_ref,
                "scoring_model": scoring_model,
                "expected_mean": mean,
                "expected_sd": sd,
                "expected_histogram": histogram,
            }
            try:
                cursor = connection.execute(
                    PKG_STATEMENTS["update_validation_baseline"], parameters
                )
                if cursor.rowcount == 0:
                    connection.execute(
                        PKG_STATEMENTS["insert_validation_baseline"], parameters
                    )
                connection.commit()
            except sqlite3.IntegrityError:
                # `IntegrityError` ONLY, which is what the published-version triggers
                # (`validation_record_immutable`, `validation_record_insert_locked`) raise
                # through `RAISE(ABORT, ...)`. Since #525 the pair carries the one
                # sanctioned exception — a baseline row may be appended to a published
                # version — so reaching here means the write was outside it: an alteration
                # of recorded figures, or an agreement/verdict write. See the docstring:
                # that is the designed refusal, not a failure of the promote that
                # triggered it.
                #
                # `sqlite3.DatabaseError` stood here and was too wide by exactly the
                # cases that matter. A missing column — this function connects with raw
                # `sqlite3.connect`, so it never passes `open_store`'s
                # `IncompleteMigrationChainError` gate — is an `OperationalError`, and
                # swallowing it returned the same quiet `False` as the refusal. That is
                # the distant-failure mode the chain pin exists to make loud, so it is
                # left to propagate.
                connection.rollback()
                return BaselineWrite(False, BASELINE_PUBLISHED)
            return BaselineWrite(True, BASELINE_RECORDED)
        finally:
            connection.close()
    return BaselineWrite(False, BASELINE_NO_SUCH_VERSION)
