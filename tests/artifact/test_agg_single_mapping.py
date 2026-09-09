"""`TC-AGG-03` — no code path maps per-judge bands to points, and no per-judge points
column exists anywhere in the schema.

Test plan §5.12 (row form), issue #94 (TS-35). Traces to `FR-AGG-02` / `NFR-AGG-02`.
Oracle: import-graph plus schema assertion.

**Not written ahead** (the `TC-PROV-05` precedent): both halves are *prohibitions* about
the shape of the source tree and the shipped schema, meaningful from the first commit and
running in `TEST_CMD` today. The behavioural half of the same acceptance — that
aggregation maps the **median band** once and never averages per-judge points — is
`TC-AGG-01`'s worked examples, written ahead of #91. This file is the structural half: it
fails on the change that adds a second reader of the band table's points, a per-judge
points column, or a second definition of the mapping, whenever that is attempted.

**Declared predicates** (a source scan is only as honest as its convention):

- *Mapping definition* = `def points_for_band`, in exactly one module (`aeh.pkg`).
  CT-PKG-05 makes it the single canonical mapping and the only sanctioned reader of
  `criterion_band.points`. Calling the function is NOT the defect — `aeh.det` maps
  deterministic outcome bands through it (CT-PKG-C05, shipped) and `aeh.setup` uses it
  at authoring time — so a closed caller list would flag designed callers, not defects.
  What fires on the defect the plan names: a **second definition** of the mapping, a
  **direct read** of the band table's points outside `aeh.pkg` (bypassing the canonical
  function is how a per-judge average re-enters), or `points` entering a statement that
  touches the per-judge `verdict` table.
- The behavioural teeth for "no code path maps per-judge bands to points" are
  `TC-AGG-01`'s worked examples (median-then-map vs map-then-average on a non-linear
  table); this file is the structural guard that runs in the gate today and forever.
- SQL predicates are applied **per string literal** (via `ast`), never per file — prose
  that mentions verdicts and points paragraphs apart must not false-positive.
- The live-schema half enumerates the real migrated tiers and checks the `verdict` table
  for band-present / points-absent. It deliberately does **not** pin today's full column
  set: CT-JUDGE-06 mandates a persisted verdict carrying `band_ordinal`,
  `evidence_sufficient`, `self_confidence` and a nullable `cited_spans` (landing with
  M-JUDGE), and a guard that reds on a conforming landing would be a false alarm. The
  defect named here — a points column, on the verdict table or anywhere — is caught by
  the points-absence check plus the schema-wide points-table sweep.
"""

from __future__ import annotations

import ast
import re

from aeh.store import open_store

_ALLOWED_POINTS_TABLES = {("package", "band"), ("cohort", "criterion_score")}

_SELECT_POINTS_FROM_BAND = re.compile(
    r"SELECT[^;]*\bpoints\b[^;]*\bFROM\s+band\b"
    r"|SELECT\s+\*[^;]*\bFROM\s+band\b",  # the wildcard read a row["points"] index consumes
    re.IGNORECASE | re.DOTALL,
)
_VERDICT_TOUCHES_POINTS = re.compile(
    r"\bverdict\b[^;]*\bpoints\b|\bpoints\b[^;]*\bFROM[^;]*\bverdict\b",
    re.IGNORECASE | re.DOTALL,
)


def test_tc_agg_03_no_per_judge_points_column_exists_anywhere_in_the_schema(tmp_data_dir):
    """`TC-AGG-03` schema half (`FR-AGG-02`, artifact assertion / rung 0, P0) — sweep
    every migrated tier: the `verdict` table carries exactly its declared columns (no
    points), and the only tables with a `points` column are the band definition table
    (M-PKG) and the aggregate `criterion_score` itself."""
    store = open_store(tmp_data_dir)
    tiers = (
        ("package", store.package("pkg-agg-03")),
        ("cohort", store.cohort("c-agg-03")),
        ("durable", store.durable()),
    )

    points_tables: set[tuple[str, str]] = set()
    for tier_name, handle in tiers:
        tables = [row["name"] for row in handle.query(
            "SELECT name FROM sqlite_master WHERE type='table'")]
        for table in tables:
            # Interpolated deliberately: the name comes from this store's own
            # sqlite_master, not from any external input.
            columns = {row["name"] for row in handle.query(f"PRAGMA table_info({table})")}
            if "points" in columns:
                points_tables.add((tier_name, table))
            if table == "verdict":
                # band-present / points-absent, not a pinned column set: CT-JUDGE-06
                # grows this table (band_ordinal, evidence_sufficient, self_confidence,
                # nullable cited_spans) when M-JUDGE lands, and a guard that reds on a
                # conforming landing is a false alarm. The defect named here is the
                # points column; the sweep below catches it on any table.
                assert "band" in columns and "points" not in columns, (
                    f"the verdict table carries {sorted(columns)} — a judge's verdict "
                    "names a band and carries no points (CT-JUDGE-06); a per-judge "
                    "points column IS the RISK-05 defect in schema form"
                )

    assert points_tables <= _ALLOWED_POINTS_TABLES, (
        f"tables carrying a points column outside the sanctioned set: "
        f"{sorted(points_tables - _ALLOWED_POINTS_TABLES)} — only the band definition "
        "(M-PKG) and the aggregate criterion_score may carry points (TC-AGG-03, "
        "FR-AGG-02's deliberate absences)"
    )


def test_tc_agg_03_the_mapping_has_one_definition_and_no_per_judge_readers(repo_root):
    """`TC-AGG-03` source half (`NFR-AGG-02`, artifact assertion / rung 0, P0) — across
    `src/aeh`: `points_for_band` is defined in exactly one module; no module outside
    `aeh.pkg` reads the band table's points directly; and no statement anywhere brings
    `points` together with the per-judge `verdict` table."""
    sources = {
        path.name: path.read_text(encoding="utf-8")
        for path in sorted((repo_root / "src" / "aeh").glob("*.py"))
    }

    defining = [name for name, text in sources.items() if "def points_for_band" in text]
    assert defining == ["pkg.py"], (
        f"points_for_band is defined in {defining} — the band→points mapping is applied "
        "in exactly one place in the source (NFR-AGG-02; CT-PKG-05)"
    )

    def sql_literals(text: str) -> list[str]:
        """Every string constant in the module — the SQL statements live here, and
        scanning per literal keeps the predicates statement-scoped."""
        parsed = ast.parse(text)
        return [
            node.value
            for node in ast.walk(parsed)
            if isinstance(node, ast.Constant) and isinstance(node.value, str)
        ]

    direct_readers = {
        name
        for name, text in sources.items()
        if name != "pkg.py"
        and any(_SELECT_POINTS_FROM_BAND.search(lit) for lit in sql_literals(text))
    }
    assert not direct_readers, (
        f"{sorted(direct_readers)} read the band table's points directly — "
        "points_for_band is the only sanctioned reader of criterion_band.points "
        "(CT-PKG-05); bypassing it is how a per-judge mapping re-enters the source"
    )

    verdict_touchers = {
        name
        for name, text in sources.items()
        if any(_VERDICT_TOUCHES_POINTS.search(lit) for lit in sql_literals(text))
    }
    assert not verdict_touchers, (
        f"{sorted(verdict_touchers)} bring points together with the per-judge verdict "
        "table — a verdict names a band and carries no points (TC-AGG-03: no code path "
        "maps per-judge bands to points; FR-AGG-02's deliberate absence)"
    )
