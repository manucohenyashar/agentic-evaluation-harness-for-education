"""The long-horizon export (one JSON Lines file per administration) and the analytical export."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from .promotion import _per_criterion_kappas
from .service import ValidationStats


#: The long-horizon record schema (`FR-STATS-23`), pinned because the test plan left it
#: open (`Q-20`) and an export nobody can parse next year is not an export. Bumped only
#: when a field's MEANING changes; adding a field at the end is not a bump, because a
#: reader that ignores unknown keys keeps working.
LONG_HORIZON_SCHEMA_VERSION = 1


#: One record per label, in this order. The order is part of the contract: JSON Lines is
#: read by line-oriented tools, and a stable key order makes a diff between two exports
#: legible instead of a reshuffle.
#:
#: | field | meaning |
#: |---|---|
#: | `schema_version` | `LONG_HORIZON_SCHEMA_VERSION`, on every line so a reader can branch per line rather than needing a header |
#: | `administration_id` | the administration the label belongs to — `label.cohort_id`, the dimension `#118`'s validation record stamps |
#: | `label_id` | the label's own id, unique within the administration |
#: | `criterion_id` | which criterion was judged |
#: | `label_type` | `blind` / `review` / … — what KIND of label this is, which decides admissibility |
#: | `evaluation_mode` | `judged` or `deterministic` (`FR-PKG-22`) |
#: | `routing` | the routing arm the label was collected under (`CT-REVIEW-07`) |
#: | `origin` | the evidence class (`FR-STATS-14`) |
#: | `saw_system_output` | 1/0/`null` — `null` is UNRECORDED and is not a 0 (`FR-STATS-22`) |
#: | `system_band` | the band the system proposed |
#: | `teacher_band` | the band the teacher chose |
#: | `agreed` | 1/0/`null` — whether the two matched (`FR-REVIEW-21`) |
#: | `band_distance` | ordinal distance between them, `null` where the band scale was not in hand |
#: | `package_version_id` | which package version the judgement was about |
#: | `assignment_type` | the population scope the package declared, `null` when it declared none |
#: | `panel_config` | the panel's shape for the run that produced the label |
#: | `review_seconds` | how long the review took |
#: | `recorded_at` | when the label was written |
#:
#: Every value is a JSON scalar or `null`. A `null` always means NOT RECORDED — never a
#: zero, an empty string or a false. That distinction is the whole reason the statistics
#: refuse to coerce (`FR-STATS-22`), and an export that flattened it would hand a future
#: analyst the coercion this system spent its design avoiding.
LONG_HORIZON_RECORD_FIELDS: tuple[str, ...] = (
    "schema_version",
    "administration_id",
    "label_id",
    "criterion_id",
    "label_type",
    "evaluation_mode",
    "routing",
    "origin",
    "saw_system_output",
    "system_band",
    "teacher_band",
    "agreed",
    "band_distance",
    "package_version_id",
    "assignment_type",
    "panel_config",
    "review_seconds",
    "recorded_at",
)


#: The file an unclaimed label lands in. `#118`'s claim stamps `label.cohort_id` when a
#: validation record is written, so an unclaimed label has none — and it still has to land
#: SOMEWHERE, or the export silently holds fewer labels than the store does.
#:
#: Its RECORD carries `administration_id: null`, not this string: an unclaimed label and a
#: label belonging to an administration someone named "unclaimed" are different facts, and
#: a reader must be able to tell them apart. The filename cannot collide either, because
#: every real administration's file carries a digest suffix and this one does not.
UNCLAIMED_ADMINISTRATION = "unclaimed"


def _long_horizon_record(label: Any) -> dict[str, Any]:
    """One label as an export record, in the declared field order, with missing values kept as
    `null`."""
    row = getattr(label, "_row", None)
    # The stored row is the source. `_StoredLabel`'s named attributes are the FILTER's
    # reading of it and are deliberately lossy — `criterion_id`, `label_type` and
    # `evaluation_mode` are coerced to `""` there — so falling back to them per field
    # would turn a NULL into an empty string and break this schema's one invariant. The
    # attributes are used only for a label that carries no row at all (a rung-0 instance
    # built from doubles), where they are the only reading there is.
    source: Mapping[str, Any]
    if row:
        source = row
    else:
        # `cohort_id` explicitly: it is the STORE's name for the administration, and the
        # record's field is `administration_id`, so reading only the record's field names
        # would leave every rung-0 label unattributed.
        source = {
            name: getattr(label, name, None)
            for name in (*LONG_HORIZON_RECORD_FIELDS, "cohort_id")
        }

    record: dict[str, Any] = {}
    for name in LONG_HORIZON_RECORD_FIELDS:
        # Built by walking the declared tuple, so the emitted key order IS the declared
        # order by construction. An earlier draft inserted two keys first and skipped
        # them in the loop, which agreed with the declaration only because they happened
        # to be its first two entries — reordering the tuple silently diverged them.
        if name == "schema_version":
            record[name] = LONG_HORIZON_SCHEMA_VERSION
            continue
        if name == "administration_id":
            claimed = source.get("cohort_id")
            record[name] = str(claimed) if claimed else None
            continue
        value = source.get(name)
        # Only JSON scalars cross the boundary. Anything else is stringified rather than
        # silently dropped: a record that quietly loses a field is worse than one
        # carrying a value a reader has to interpret.
        if value is not None and not isinstance(value, (str, int, float, bool)):
            value = str(value)
        record[name] = value
    return record


def _administration_filename(administration_id: str | None) -> str:
    """The export file name for an administration: readable, and never the same for two
    administrations.

    An administration id is data, and data does not choose paths — so anything that could
    escape the directory or confuse a shell is replaced. But sanitising alone is not
    enough, and the failure it causes is silent data loss rather than a crash: two
    different ids that sanitise to one name write to one file, and the second write
    TRUNCATES the first. The worst case needs no special characters at all — `A1` and
    `a1` are one filename on Windows and macOS, so an export of both would report success
    while holding only one of them.

    So every real administration's name carries a digest of its EXACT id. Two ids that
    differ at all — in case, in punctuation, in anything — differ in the digest, and the
    readable prefix stays a prefix rather than a promise. The digest is of the id alone,
    so a file's name does not depend on which other administrations happen to exist,
    which is what keeps the export reproducible across data sets.

    The unclaimed file is the one name with no digest, which is exactly why a real
    administration named `unclaimed` cannot collide with it.
    """
    if administration_id is None:
        return f"{UNCLAIMED_ADMINISTRATION}.jsonl"
    text = str(administration_id)
    safe = "".join(ch if (ch.isalnum() or ch in "-_.") else "_" for ch in text)
    digest = hashlib.sha256(text.encode("utf-8")).hexdigest()[:12]
    return f"{safe}-{digest}.jsonl" if safe else f"administration-{digest}.jsonl"


def long_horizon_export(
    stats: "ValidationStats", data_dir: Path | str | None = None
) -> tuple[Path, ...]:
    """Write one read-only JSON Lines file per administration under the data directory's `exports/`
    (FR-STATS-23, ADR-19).

    More detail: `docs/code-notes/stats.md`, section `exports.py: long_horizon_export`.
    """
    target = Path(data_dir) if data_dir is not None else stats._data_dir
    if target is None:
        raise ValueError(
            "long_horizon_export() needs a data directory: pass data_dir=, or export an "
            "instance built by open_stats(), which carries the directory it read."
        )
    export_dir = Path(target) / "exports"
    export_dir.mkdir(parents=True, exist_ok=True)

    # Keyed by the EXACT id (and `None` for unclaimed), never by the filename: grouping
    # by a sanitised name is what would merge two administrations into one file.
    by_administration: dict[str | None, list[dict[str, Any]]] = {}
    for label in stats._labels:
        record = _long_horizon_record(label)
        by_administration.setdefault(record["administration_id"], []).append(record)

    written: list[Path] = []
    for administration_id, records in sorted(
        by_administration.items(), key=lambda item: (item[0] is not None, item[0] or "")
    ):
        # Sorted by label id: the file's order is a property of the DATA, not of the
        # order rows came back, so two exports of the same administration are identical
        # even if the store returned them differently.
        records.sort(key=lambda record: str(record["label_id"]))
        lines = "".join(
            # `allow_nan=False`: Python emits bare `Infinity`/`NaN` for a non-finite
            # float, which is not JSON (RFC 8259) and would break the one promise every
            # line makes. A REAL column holding one refuses here, by name, rather than
            # writing an archive no parser accepts.
            json.dumps(
                record, separators=(",", ":"), sort_keys=False, allow_nan=False
            )
            + "\n"
            for record in records
        )
        path = export_dir / _administration_filename(administration_id)
        # `newline=""` keeps the "\n" above the only line ending on every platform: this
        # suite runs on Windows, where the default would translate each one to CRLF and
        # make the same export differ between machines.
        with open(path, "w", encoding="utf-8", newline="") as handle:
            handle.write(lines)
        written.append(path)
    return tuple(sorted(written))


def analytical_export(
    stats: "ValidationStats", data_dir: Path | str | None = None
) -> dict[str, Any]:
    """The optional analytical export (NFR-STATS-03): one JSON file of figures (per-criterion
    figures, the weakest criterion per population, the counters, the narrative-quality report)
    under the data directory's `exports/`.

    The clause's *"optional"* and *"never touches the scoring pipeline"* are
    both held in the shape: the export reads the labels the instance already
    holds (its constructor read them; nothing here reopens a database), opens
    no connection, takes no lock, and writes only under ``exports/`` — so it
    can run beside a live scoring run without contending with it, and the
    write audit's attribution sees exactly one file write, on a path that
    names what it is. The cost of that honesty is that the export reports the
    labels the instance was built with; an export of fresher data asks
    ``open_stats`` first."""
    target = Path(data_dir) if data_dir is not None else stats._data_dir
    if target is None:
        raise ValueError(
            "analytical_export() needs a data directory: pass data_dir=, or "
            "export an instance built by open_stats(), which carries the "
            "directory it read."
        )
    export_dir = target / "exports"
    export_dir.mkdir(parents=True, exist_ok=True)
    admissible = stats.admissible_labels()
    kappas = _per_criterion_kappas(admissible, stats._band_counts)
    figures = []
    for criterion in sorted(kappas):
        criterion_n = sum(
            1
            for label in admissible
            if (getattr(label, "criterion_id", "") or "") == criterion
        )
        figures.append(
            {"criterion_id": criterion, "n": criterion_n, "kappa": kappas[criterion]}
        )
    report = stats.narrative_quality()
    quality = {
        "citation_validity_rate": report.citation_validity_rate,
        "hallucinated_claim_rate": report.hallucinated_claim_rate,
        "teacher_rating": report.teacher_rating,
        "channel_declared": report.channel_declared,
    }
    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "label_count": len(stats._labels),
        "admissible_n": len(admissible),
        "figures": figures,
        "counters": stats.observability_counters(),
        "narrative_quality": quality,
    }
    export_path = export_dir / "validation-analytics.json"
    export_path.write_text(
        json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8"
    )
    return {
        "export_path": str(export_path),
        "criteria": sorted(kappas),
        "admissible_n": len(admissible),
        "figure_count": len(figures),
    }
