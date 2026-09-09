"""`TC-AGG-16` — the write sets of `M-AGG` and `M-SYNTH` are disjoint.

Test plan §5.12 (row form: Artifact assertion / rung 0), issue #95 (TS-36). Traces to
`FR-AGG-14`; CT-AGG-11 ("writes `criterion_score` and nothing else"; §7.2 Rule 3).

**Not written ahead** (the `TC-AGG-03` precedent): the case is a *prohibition* about
the shape of the source tree, meaningful from the first commit and running in
`TEST_CMD` today. `aeh.agg` and `aeh.synth` do not exist yet — the guard is vacuously
satisfied by their absence and fires the moment either module appears carrying the
other's write. The behavioural teeth (that aggregation actually writes only
`criterion_score`) are the integration cases'; this file is the structural guard that
never sleeps.

**Declared predicates** (a source scan is only as honest as its convention):

- *Write to a table* = a statement literal in the module containing `INSERT INTO
  <table>` / `INSERT OR ... INTO <table>` / `UPDATE <table>` / `DELETE FROM <table>`.
  SQL lives in statement literals (the `TC-AGG-03` per-literal convention); DDL
  (`CREATE TABLE`) is not a write and is not scanned — `aeh.store` owns the schema for
  every tier. The scan is recursive (`rglob`), and the sanctioned sets are matched
  against the path relative to `src/aeh`, so a write hiding in a future subpackage
  (`aeh/synth/helpers.py`) is caught too — subpackage modules inherit nothing.
- *Sanctioned writers* of `criterion_score` today: `store.py` (DDL and the audit
  purge statements) and `det.py` (the deterministic upsert — TC-AGG-13's
  pass-through input). `agg.py` joins this set at #93 (CT-AGG-11 makes it the
  module's whole write set) and `review.py` at #109 (CT-REVIEW-06: a review action
  "writes through criterion_score and never a grade"). Allowing a module that does
  not exist yet is deliberate: the guard must not red on a conforming landing.
- *Sanctioned writers* of `narrative`: `store.py` (DDL) — `synth.py` joins at #89's
  synthesis story (FR-SYNTH-01's generated-narrative write).
- The defect the case names — `M-AGG` reaching `narrative`, `M-SYNTH` reaching
  `criterion_score` — is caught the day it is written, on either side of the landing.
"""

from __future__ import annotations

import ast
import re

_NARRATIVE_WRITERS_ALLOWED = {"store.py", "synth.py"}
_CRITERION_SCORE_WRITERS_ALLOWED = {"store.py", "det.py", "agg.py", "review.py"}

_WRITE_TO_NARRATIVE = re.compile(
    r"\bINSERT\b[^;]*\bINTO\s+narrative\b|\bUPDATE\s+narrative\b|\bDELETE\s+FROM\s+narrative\b",
    re.IGNORECASE | re.DOTALL,
)
_WRITE_TO_CRITERION_SCORE = re.compile(
    r"\bINSERT\b[^;]*\bINTO\s+criterion_score\b|\bUPDATE\s+criterion_score\b"
    r"|\bDELETE\s+FROM\s+criterion_score\b",
    re.IGNORECASE | re.DOTALL,
)


def _statement_literals(path) -> list[str]:
    """Every string constant in the module — the SQL lives here, and scanning per
    literal keeps the predicates statement-scoped (the TC-AGG-03 convention)."""
    parsed = ast.parse(path.read_text(encoding="utf-8"))
    return [
        node.value
        for node in ast.walk(parsed)
        if isinstance(node, ast.Constant) and isinstance(node.value, str)
    ]


def test_tc_agg_16_the_m_agg_and_m_synth_write_sets_are_disjoint(repo_root):
    """`TC-AGG-16` (`FR-AGG-14`, artifact assertion / rung 0, import-graph
    assertion, P0) — across `src/aeh`: no module outside the sanctioned set carries a
    write to `narrative`, none outside its set carries a write to `criterion_score`,
    and in particular `M-AGG` has no path to `narrative` while `M-SYNTH` has none to
    `criterion_score`."""
    sources = {
        str(path.relative_to(repo_root / "src" / "aeh")): path
        for path in sorted((repo_root / "src" / "aeh").rglob("*.py"))
    }

    narrative_writers = {
        name
        for name, path in sources.items()
        if any(_WRITE_TO_NARRATIVE.search(lit) for lit in _statement_literals(path))
    }
    assert narrative_writers <= _NARRATIVE_WRITERS_ALLOWED, (
        f"{sorted(narrative_writers - _NARRATIVE_WRITERS_ALLOWED)} write `narrative` "
        "— only M-SYNTH may (FR-AGG-14: M-AGG has no path to narrative, §7.2 Rule 3's "
        "write-set disjointness)"
    )
    assert "agg.py" not in narrative_writers, (
        "aeh.agg carries a write to narrative — the whole of the TC-AGG-16 defect on "
        "the M-AGG side (CT-AGG-11: M-AGG writes criterion_score and nothing else)"
    )

    criterion_score_writers = {
        name
        for name, path in sources.items()
        if any(_WRITE_TO_CRITERION_SCORE.search(lit) for lit in _statement_literals(path))
    }
    assert criterion_score_writers <= _CRITERION_SCORE_WRITERS_ALLOWED, (
        f"{sorted(criterion_score_writers - _CRITERION_SCORE_WRITERS_ALLOWED)} write "
        "`criterion_score` — M-STORE's DDL, M-DET's deterministic upsert, M-AGG's "
        "aggregate write and M-REVIEW's write-through are the sanctioned set; M-SYNTH "
        "is not in it (FR-AGG-14: no write path to criterion_score)"
    )
    assert "synth.py" not in criterion_score_writers, (
        "aeh.synth carries a write to criterion_score — the whole of the TC-AGG-16 "
        "defect on the M-SYNTH side (§7.2 Rule 3)"
    )
