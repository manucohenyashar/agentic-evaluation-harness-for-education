"""`TS-89` (issue #383) — `TC-STATS-30`: the long-horizon JSON Lines export (`FR-STATS-23`,
ADR-19 amending `NFR-STATS-03`).

| Input | Expected |
|---|---|
| two administrations, A1 (40 labels) and A2 (10) | `exports/` holds exactly 2 `.jsonl` files; line counts 40 and 10; every line parses as JSON; the export performs no write to any tier; a second export of A1 is byte-identical; no Parquet/DuckDB import in `stats.py` |

**Why JSON Lines and not Parquet.** The artifact has to be readable in five years by anything
that can read a line — no engine, no version-matched reader, no binary schema to recover. That
is ADR-19's whole reason, and the "no Parquet/DuckDB import" clause is what keeps it true: one
`import duckdb` and the archive silently acquires a dependency that has to still exist and
still match when someone opens the file a decade later.

**Byte-identical re-export is a property of the data, not of luck.** Records are ordered by
label id, keys are written in the declared order, and **nothing carries a wall clock** — the
generation time is exactly the field that would make every export differ from every other,
which is why this document has no `generated_at` while `analytical_export` has one. An archive
whose bytes change on every run cannot be diffed, deduplicated or checksummed.

**"No write to any tier" is what lets the export run beside a live scoring run.** The labels
are the ones the instance already holds, so the export opens no connection and takes no lock.
Asserted by fingerprinting every store file before and after: a lock-free read that quietly
touched a tier would still corrupt a running cohort's assumptions.

**Isolation: rung 2** — a real store on disk and the real export, so the files and the
untouched tiers are both observable.
"""

from __future__ import annotations

import ast
import hashlib
import json
import pathlib
from dataclasses import dataclass

import pytest

import aeh.stats as stats_module
from aeh.stats import ValidationStats, long_horizon_export

pytestmark = pytest.mark.integration

A1, A2 = "admin-2026-spring", "admin-2026-autumn"
A1_LABELS, A2_LABELS = 40, 10

#: The engines ADR-19 replaced. An import of any of them turns a five-year archive into one
#: that needs a matching reader to open.
FORBIDDEN_ENGINES = ("duckdb", "pyarrow", "parquet", "fastparquet")


@dataclass(frozen=True)
class _Label:
    """An admissible label carrying an administration id — the export's grouping key.

    The field is `cohort_id`, not `administration_id`: the store's name for the administration
    is the cohort, and `_long_horizon_record` maps it onto the record's `administration_id`
    deliberately, "so reading only the record's field names would leave every rung-0 label
    unattributed". A fixture that set `administration_id` here writes every label to
    `unclaimed.jsonl` and the grouping assertions fail for a reason that is about the fixture.
    """

    label_id: str
    cohort_id: str
    criterion_id: str = "C1"
    label_type: str = "blind"
    evaluation_mode: str = "judged"
    saw_system_output: int = 0
    band: int = 3
    teacher_band: int = 3


def _population():
    return [
        *(
            _Label(f"a1-{index:03d}", A1)
            for index in range(A1_LABELS)
        ),
        *(
            _Label(f"a2-{index:03d}", A2)
            for index in range(A2_LABELS)
        ),
    ]


def _fingerprint(root: pathlib.Path) -> dict[str, str]:
    """Every file under `root` outside `exports/`, by content hash."""
    prints: dict[str, str] = {}
    for path in sorted(root.rglob("*")):
        if not path.is_file() or "exports" in path.relative_to(root).parts:
            continue
        prints[str(path.relative_to(root))] = hashlib.sha256(
            path.read_bytes()
        ).hexdigest()
    return prints


@pytest.fixture
def export_world(tmp_data_dir):
    """A real data directory with real tier files on disk, and stats over the two cohorts.

    A run is seeded rather than just opening and closing a store: the tiers are created
    lazily, so an opened-and-closed store leaves nothing on disk and the "wrote to no tier"
    fingerprint would compare two empty dicts.
    """
    from aeh.store import open_store
    from tests.support.orch_run import seed_run

    store = open_store(tmp_data_dir)
    try:
        seed_run(
            store,
            submissions=("S001",),
            criteria=({"criterion_id": "C1", "kind": "open", "scoring_model": "atomic"},),
        )
    finally:
        store.close()
    return tmp_data_dir, ValidationStats(labels=_population())


# --- TC-STATS-30 ----------------------------------------------------------------------------


def test_tc_stats_30_one_file_per_administration_with_the_right_line_counts(export_world):
    """Exactly two `.jsonl` files, of 40 and 10 lines.

    The counts are the assertion that the grouping key is the administration id. An export
    keyed on the sanitised *filename* would merge two administrations whose names differ only
    in punctuation, and an export that ignored the key would write one file of 50.
    """
    data_dir, stats = export_world

    written = long_horizon_export(stats, data_dir)

    assert len(written) == 2, f"the export wrote {len(written)} files, not 2: {written}"
    files = sorted((data_dir / "exports").glob("*.jsonl"))
    assert len(files) == 2, f"exports/ holds {len(files)} .jsonl files: {files}"

    counts = sorted(
        len(path.read_text(encoding="utf-8").splitlines()) for path in files
    )
    assert counts == sorted((A1_LABELS, A2_LABELS)), (
        f"line counts are {counts}, not {sorted((A1_LABELS, A2_LABELS))} — one record per "
        "label, grouped by administration"
    )


def test_tc_stats_30_every_line_is_a_self_describing_json_record(export_world):
    """Each line parses on its own as a JSON object carrying its administration id.

    Per-line rather than per-file: the format's whole promise is that a reader can take one
    line at a time with no engine. A file that parsed only as a whole — a JSON array, say —
    would satisfy "valid JSON" and break exactly that promise.
    """
    data_dir, stats = export_world
    long_horizon_export(stats, data_dir)

    for path in sorted((data_dir / "exports").glob("*.jsonl")):
        for number, line in enumerate(
            path.read_text(encoding="utf-8").splitlines(), start=1
        ):
            try:
                record = json.loads(line)
            except ValueError as error:  # pragma: no cover — the failure message is the point
                pytest.fail(f"{path.name} line {number} is not JSON: {error}")
            assert isinstance(record, dict), (
                f"{path.name} line {number} is a {type(record).__name__}, not an object"
            )
            assert record.get("administration_id") in (A1, A2), (
                f"{path.name} line {number} carries administration_id "
                f"{record.get('administration_id')!r}; a self-describing record names its own "
                "administration rather than relying on the filename"
            )


def test_tc_stats_30_a_second_export_is_byte_identical(export_world):
    """Re-exporting the same labels produces the same bytes.

    The property that makes the file an archive rather than a report. A `generated_at`, an
    unordered record list, or a dict whose key order follows insertion would each break it,
    and none of them would break any other assertion in this file.
    """
    data_dir, stats = export_world

    first = {
        path.name: path.read_bytes() for path in long_horizon_export(stats, data_dir)
    }
    second = {
        path.name: path.read_bytes() for path in long_horizon_export(stats, data_dir)
    }

    assert first.keys() == second.keys(), (
        f"the second export wrote different files: {sorted(first)} then {sorted(second)}"
    )
    differing = [name for name in first if first[name] != second[name]]
    assert differing == [], (
        f"re-exporting changed the bytes of {differing}. Nothing in the record may carry a "
        "wall clock, and the order must be a property of the data (FR-STATS-23)"
    )


def test_tc_stats_30_the_export_writes_to_no_tier(export_world):
    """Every store file is byte-identical before and after — only `exports/` changes.

    The export is meant to run beside a live scoring run, which it can only do if it takes no
    lock and writes nothing. Fingerprinting the whole directory catches a write to any tier,
    including one made through a connection the export opened "just to check".
    """
    data_dir, stats = export_world
    before = _fingerprint(data_dir)
    assert before, "the fixture wrote no store files, so the comparison is vacuous"

    long_horizon_export(stats, data_dir)

    after = _fingerprint(data_dir)
    changed = sorted(
        name for name in set(before) | set(after) if before.get(name) != after.get(name)
    )
    assert changed == [], (
        f"the export changed store files outside exports/: {changed}. FR-STATS-23's export "
        "opens no connection and takes no lock, which is what lets it run beside a live run"
    )


def _top_level_imports(source: str) -> set[str]:
    """Every root package `source` imports, however it spells the import.

    Parsed rather than grepped: the module's own docstring explains what ADR-19 *replaced*, and
    a text search would report that explanation as the dependency it forbids. Only a real
    `import` or `from … import` statement counts.
    """
    tree = ast.parse(source)
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name.split(".")[0].lower() for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module.split(".")[0].lower())
    return imported


def test_tc_stats_30_stats_imports_no_columnar_engine():
    """`stats.py` imports no Parquet or DuckDB reader."""
    source = pathlib.Path(stats_module.__file__).read_text(encoding="utf-8")

    offenders = sorted(_top_level_imports(source) & set(FORBIDDEN_ENGINES))
    assert offenders == [], (
        f"aeh.stats imports {offenders}. ADR-19 chose JSON Lines so the archive can be read "
        "in five years by anything that reads a line; a columnar engine puts a "
        "version-matched reader between the file and whoever opens it"
    )


def test_tc_stats_30_the_engine_scan_would_see_an_import(export_world):
    """The scan's control — it recognises the import shape it forbids.

    Without it, a scan looking at the wrong attribute would report "no offenders" for a module
    that imported every engine on the list.
    """
    tree = ast.parse("import duckdb\nfrom pyarrow import parquet\n")

    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name.split(".")[0].lower() for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module.split(".")[0].lower())

    assert imported & set(FORBIDDEN_ENGINES) == {"duckdb", "pyarrow"}, (
        f"the scan's matching rule saw {sorted(imported)}; it does not recognise the two "
        "import shapes it is meant to forbid"
    )
