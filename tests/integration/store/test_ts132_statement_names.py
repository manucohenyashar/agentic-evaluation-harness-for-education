"""TS-132 (#543): import order can never change which SQL a statement name runs.

| Case | Oracle |
|---|---|
| TC-STORE-28 (a) | In a subprocess per order (alphabetical, then reverse), every `aeh` module is imported and every `*STATEMENTS` dictionary scanned: no name carries two SQL texts (design 1.9 §3.2's scan returns 0), and each name resolves to the same text in both orders |
| TC-STORE-28 (b) | Re-registering a name the shared `aeh.store.STATEMENTS` holds, with different SQL, raises `StatementConflictError` (a `ValueError`) naming both modules, and the registry is unchanged |
| TC-STORE-28 (c) | Re-registering with byte-identical SQL raises nothing |

Deviation from the plan row, disclosed: the row names `select_run` for (b). #511 resolved the
conflicts by renaming the minority side, and M-GRADE's `select_run` (the one the shared registry
carried) is now `select_grade_run`, so `select_run` is no longer in the shared registry. The case
uses a name the registry does hold (M-INGEST's `select_document_head`, the name TC-REG-07 was
about), which is the behaviour the row asks for.

Rung 1: each order runs in its own interpreter, because import order is a property of a
process — within one pytest process every module is already imported.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[3]

_SCAN = r"""
import importlib, json, pkgutil, sys
import aeh
from aeh.store import Statement
mods = sorted(m.name for m in pkgutil.iter_modules(aeh.__path__))
if sys.argv[1] == "reverse":
    mods = mods[::-1]
for m in mods:
    importlib.import_module("aeh." + m)
texts, seen = {}, set()
for m in mods:
    for attr, val in vars(sys.modules["aeh." + m]).items():
        if not attr.endswith("STATEMENTS") or not isinstance(val, dict) or id(val) in seen:
            continue
        seen.add(id(val))
        for name, st in val.items():
            if isinstance(st, Statement):
                texts.setdefault(name, set()).add(str(st))
print(json.dumps({
    "modules": len(mods),
    "conflicts": sorted(n for n, v in texts.items() if len(v) > 1),
    "resolved": {n: sorted(v)[0] for n, v in texts.items()},
}))
"""

_REGISTER = r"""
import json
import aeh.agg, aeh.det, aeh.extract, aeh.grade, aeh.ingest, aeh.integ, aeh.judge, aeh.orch, aeh.pkg, aeh.review, aeh.synth
from aeh.store import STATEMENTS, Statement, StatementConflictError
name = "select_document_head"
before = dict(STATEMENTS)
out = {"present": name in STATEMENTS}
try:
    STATEMENTS[name] = Statement("SELECT 1 AS not_the_same_sql")
    out["conflict"] = None
except StatementConflictError as error:
    out["conflict"] = str(error)
    out["is_value_error"] = isinstance(error, ValueError)
out["unchanged"] = dict(STATEMENTS) == before
try:
    STATEMENTS[name] = Statement(str(before[name]))
    out["identical_ok"] = True
except Exception as error:
    out["identical_ok"] = repr(error)
out["unchanged_after_identical"] = dict(STATEMENTS) == before
print(json.dumps(out))
"""


def _run(script: str, *args: str) -> dict:
    env = {**os.environ, "PYTHONPATH": os.pathsep.join([str(REPO / "src"), str(REPO)])}
    done = subprocess.run([sys.executable, "-c", script, *args], capture_output=True, text=True,
                          env=env, cwd=str(REPO), timeout=300)
    assert done.returncode == 0, f"the subprocess failed:\n{done.stderr[-2000:]}"
    return json.loads(done.stdout.strip().splitlines()[-1])


@pytest.mark.integration
def test_tc_store_28_a_every_name_has_one_sql_text_in_both_import_orders():
    alphabetical = _run(_SCAN, "alphabetical")
    reverse = _run(_SCAN, "reverse")
    assert alphabetical["modules"] >= 20, alphabetical["modules"]
    assert alphabetical["conflicts"] == [], (
        f"statement names with two SQL texts (alphabetical import): {alphabetical['conflicts']} "
        "(FR-STORE-16: one SQL text per name)")
    assert reverse["conflicts"] == [], (
        f"statement names with two SQL texts (reverse import): {reverse['conflicts']}")
    differing = sorted(name for name, sql in alphabetical["resolved"].items()
                       if reverse["resolved"].get(name) != sql)
    assert not differing, f"these names resolve to different SQL by import order: {differing}"


@pytest.mark.integration
def test_tc_store_28_b_c_a_conflicting_registration_is_refused_and_an_identical_one_is_not():
    out = _run(_REGISTER)
    assert out["present"], "fixture: the shared registry must hold the name being re-registered"
    assert out["conflict"], "re-registering a held name with different SQL raised nothing"
    assert out["is_value_error"], "StatementConflictError must be a ValueError (FR-STORE-16)"
    assert "aeh.ingest" in out["conflict"] and "__main__" in out["conflict"], (
        f"the refusal must name both modules: {out['conflict']!r}")
    assert out["unchanged"], "a refused registration changed the registry"
    assert out["identical_ok"] is True, f"a byte-identical re-registration raised: {out['identical_ok']}"
    assert out["unchanged_after_identical"], "an identical re-registration changed the registry"
