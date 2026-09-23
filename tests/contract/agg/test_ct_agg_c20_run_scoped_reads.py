"""`TS-95` (issue #389) — `TC-AGG-C20`: every score read is run-scoped (`CT-AGG-20`,
`FR-AGG-15`, gap-fix test plan §5 / §6).

| Case | Rung | Oracle |
|---|---|---|
| `TC-AGG-C20` | 0 | SQL scan of every declared statement and every string literal in `aeh/*.py` that reads `criterion_score`. Each has a `run_id` predicate or join |

**The safety property.** Since #359 `criterion_score` is keyed by run. A read that forgets the
`run_id` predicate does not fail — it silently pools every run the cohort has ever had, and the
caller gets a total, a band or a finding computed over two runs' work. `FR-GRADE-18` and
`TC-GRADE-25`'s two-run isolation depend on this holding *everywhere*, not in the places somebody
remembered to test: run A's grades must be identical before and after run B lands, and one
unscoped read anywhere in the path makes that false.

**Why a static scan is the right rung.** A behavioural test can only catch the reads it happens
to drive. This is the class of defect where the missing case *is* the defect, so the oracle is
over the source: every literal that reads `criterion_score`, in every module, whether or not any
test exercises it. Rung 0, no store, no run — the cheapest level that can answer the question at
all, which is the level the requirement deserves.

**Parsed, not grepped.** The scan walks the AST and reads string constants, so a statement split
across adjacent literals — which is how most of `aeh`'s SQL is written — is seen whole. A line
scan would miss exactly those, and this repo's own `sql_scan.py` gives the same reason.

**The three exemptions are declared, not inferred**, and each is a read that *must not* be
run-scoped:

* `store.py`'s purge `DELETE` and its blob-reference `SELECT` sweep the whole cohort. A purge
  that deleted only one run's rows would leave student work behind, which is the failure
  `CT-STORE-10` exists to prevent.
* `agg.py`'s `MigrationPrecondition` is the precondition of `agg_run_scoped_score` itself — the
  migration that *added* `run_id`. It cannot filter on a column that does not exist yet.

Anything else that reads `criterion_score` without naming `run_id` fails here, and adding to the
exemption list is a deliberate edit a reviewer sees.
"""

from __future__ import annotations

import ast
import pathlib
import re

import pytest

pytestmark = pytest.mark.contract

REPO_ROOT = pathlib.Path(__file__).resolve().parents[3]
SOURCE_DIR = REPO_ROOT / "src" / "aeh"

#: A literal that reads the table, rather than merely naming it in prose.
_READS = re.compile(r"\b(?:FROM|JOIN)\s+criterion_score\b", re.IGNORECASE)
_RUN_SCOPED = re.compile(r"\brun_id\b", re.IGNORECASE)

#: Reads that must NOT carry a `run_id` predicate, by `(module, purpose)`. Each is justified in
#: the module docstring; the identifying text is matched rather than a line number so an edit
#: above the site does not spuriously fail this case.
DECLARED_EXEMPTIONS: tuple[tuple[str, str], ...] = (
    # The purge sweeps the cohort, not a run: a purge scoped to one run leaves student work
    # behind (CT-STORE-10).
    ("store.py", "DELETE FROM criterion_score"),
    ("store.py", "SELECT * FROM criterion_score"),
    # The precondition of `agg_run_scoped_score` — the migration that added `run_id`. It cannot
    # filter on a column that does not exist until it has run.
    ("agg.py", "SELECT EXISTS (SELECT 1 FROM criterion_score)"),
)


def _literals(path: pathlib.Path) -> list[tuple[int, str]]:
    """Every string constant in the module, with its line.

    Adjacent literals are concatenated by the parser, so a statement written across several
    source lines arrives here whole — which is how most of `aeh`'s SQL is written.
    """
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    return [
        (node.lineno, node.value)
        for node in ast.walk(tree)
        if isinstance(node, ast.Constant) and isinstance(node.value, str)
    ]


def _score_reads() -> list[tuple[str, int, str]]:
    """Every literal in `aeh/*.py` that reads `criterion_score`."""
    found: list[tuple[str, int, str]] = []
    for path in sorted(SOURCE_DIR.glob("*.py")):
        for line, text in _literals(path):
            if _READS.search(text):
                found.append((path.name, line, " ".join(text.split())))
    return found


def _is_exempt(module: str, sql: str) -> bool:
    return any(
        module == name and marker.lower() in sql.lower()
        for name, marker in DECLARED_EXEMPTIONS
    )


# --- TC-AGG-C20 ----------------------------------------------------------------------------


def test_tc_agg_c20_every_score_read_is_run_scoped() -> None:
    """`CT-AGG-20` — no unscoped read of `criterion_score` outside the declared exemptions.

    An unscoped read pools every run the cohort has had. It does not raise; it returns a number
    that is quietly wrong, which is why this is asserted over the source rather than waited for
    in a behavioural case.
    """
    unscoped = [
        (module, line, sql)
        for module, line, sql in _score_reads()
        if not _RUN_SCOPED.search(sql) and not _is_exempt(module, sql)
    ]
    assert unscoped == [], (
        "these reads of criterion_score carry no run_id predicate, so they pool every run the "
        "cohort has had (CT-AGG-20, FR-GRADE-18's two-run isolation):\n  "
        + "\n  ".join(f"{m}:{line}  {sql[:110]}" for m, line, sql in unscoped)
        + "\nIf one of these must be cohort-wide, add it to DECLARED_EXEMPTIONS with its reason."
    )


def test_tc_agg_c20_the_scan_actually_finds_the_reads_it_claims_to_check() -> None:
    """The scan's own positive control.

    A scan that matched nothing would pass the case above and assert precisely nothing — the
    failure mode every static oracle has. So: the reads exist, they are spread across more than
    one module, and the run-scoped majority is what the codebase actually looks like.
    """
    reads = _score_reads()
    assert len(reads) >= 10, (
        f"the scan found only {len(reads)} reads of criterion_score; the codebase has many, so "
        "the pattern has stopped matching and the invariant above is vacuous"
    )
    modules = {module for module, _line, _sql in reads}
    assert len(modules) >= 3, (
        f"the scan sees criterion_score reads in only {sorted(modules)}; it should span the "
        "aggregation, grading and review paths at least"
    )
    scoped = [r for r in reads if _RUN_SCOPED.search(r[2])]
    assert len(scoped) >= 8, (
        f"only {len(scoped)} of {len(reads)} reads are run-scoped — if the invariant above "
        "passed, it did so by exempting nearly everything"
    )


def test_tc_agg_c20_every_declared_exemption_still_exists() -> None:
    """An exemption whose site is gone is a hole nobody is watching.

    The list narrows a safety property, so it must shrink when the code does. A stale entry
    would silently excuse a *future* read that happened to match its text.
    """
    reads = _score_reads()
    stale = [
        (name, marker)
        for name, marker in DECLARED_EXEMPTIONS
        if not any(
            module == name and marker.lower() in sql.lower() for module, _line, sql in reads
        )
    ]
    assert stale == [], (
        f"DECLARED_EXEMPTIONS names sites that no longer exist: {stale}. Remove them — a stale "
        "exemption excuses a future unscoped read that happens to match its text."
    )
