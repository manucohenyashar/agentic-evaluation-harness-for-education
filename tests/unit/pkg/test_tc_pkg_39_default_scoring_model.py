"""`TC-PKG-39` (issue #896, FR-PKG-29, CT-PKG-24, FR-SETUP-14) — the default scoring model's
decision table, through M-PKG's own publish path.

Statistical-validity test plan §3.4 (story T3). A spec is published through `build_package` —
the one M-PKG write both `aeh package build` and the console's approve reach — with judged lines
that declare no `scoring`, and two that do. The oracle is the published spec (each criterion's
stored `scoring_model`) and the recorded default flag (`PackageCatalog.scoring_model_defaulted`,
read off the `scoring_model` setup-step row FR-SETUP-14 asks for).

| Criterion | Expected model | Default flag |
|---|---|---|
| aspect of an `evidence_sum` composite (ENG7's C1a, C1b) | `atomic` | true |
| exactly two bands (C4) | `atomic` | true |
| four bands (ENG7's C2) | `holistic` | true |
| `general` (ENG7's C3) | `holistic` | true |
| six bands (C5) — stands in for the plan's "three bands" | `holistic` | true |
| two bands, declared `holistic` (C6) | `holistic` | false |
| four bands, declared `atomic` (C7) | `atomic` | false |

**Plan deviation, disclosed (the "three bands" row).** A three-band line cannot be published:
FR-PKG-06 refuses an odd band count (legal sets are 2, 4 and 6 bands). The row's intent — a
judged line that is neither two-band nor an aspect takes `holistic` — is asserted on a six-band
line instead, and a separate case pins that the three-band spec is refused, so the substitution
stays honest if FR-PKG-06 ever changes.

**Isolation: rung 1** — a real Tier P store in `tmp_data_dir`, M-PKG's own build; no model call.
**Written ahead of implementation: no** — #864 (PR #922) landed the default.

Markers. None (fast tier).
"""

from __future__ import annotations

import copy
import json
import tomllib
from pathlib import Path

import pytest

import aeh.agg  # noqa: F401 — the full migration chain before the first store open (CLAUDE.md)
import aeh.det  # noqa: F401
import aeh.extract  # noqa: F401
import aeh.grade  # noqa: F401
import aeh.ingest  # noqa: F401
import aeh.integ  # noqa: F401
import aeh.judge  # noqa: F401
import aeh.orch  # noqa: F401
import aeh.pkg  # noqa: F401
import aeh.review  # noqa: F401
import aeh.synth  # noqa: F401
from aeh.pipeline.packages import build_package
from aeh.pkg import PackageCatalog
from aeh.pkg.spec_criteria import SCORING_DEFAULT_STEP
from aeh.store import open_store

REPO = Path(__file__).resolve().parents[3]
ENG7_SPEC = REPO / "docs" / "live-tests" / "config" / "eng7-read-01.package.toml"


def _bands(count: int) -> list[dict]:
    return [{"name": f"level{i}", "points": i, "descriptor": f"Level {i} of the answer."}
            for i in range(count)]


def _line(cid: str, qid: str, bands: int, scoring: str | None = None) -> dict:
    line = {"id": cid, "question": qid, "bands": _bands(bands)}
    if scoring is not None:
        line["scoring"] = scoring
    return line


def _question(qid: str, points: int) -> dict:
    return {"id": qid, "type": "open", "points": points,
            "text": f"Question {qid}: explain your reasoning.",
            "model_answer": f"A model answer for {qid}."}


def _spec(extra: list[tuple[str, dict]]) -> dict:
    """The shipped ENG7 spec (C1 an evidence_sum with aspects C1a/C1b, C2 four bands, C3
    general — none declares `scoring`) plus one question per extra judged line."""
    spec = tomllib.loads(ENG7_SPEC.read_text(encoding="utf-8"))
    spec = copy.deepcopy(spec)
    for qid, line in extra:
        spec["question"].append(_question(qid, len(line["bands"]) - 1))
        spec["criterion"].append(line)
    return spec


#: `(criterion, expected model, expected default flag)` — the plan's decision table.
DECISION_TABLE = (
    ("C1a", "atomic", True),     # aspect of an evidence_sum composite
    ("C1b", "atomic", True),     # aspect of an evidence_sum composite
    ("C4", "atomic", True),      # exactly two bands
    ("C2", "holistic", True),    # four bands
    ("C3", "holistic", True),    # general
    ("C5", "holistic", True),    # six bands (the "three bands" row's legal stand-in)
    ("C6", "holistic", False),   # two bands, declared holistic: the declaration wins
    ("C7", "atomic", False),     # four bands, declared atomic: the declaration wins
)

EXTRA_LINES = [
    ("Q4", _line("C4", "Q4", 2)),
    ("Q5", _line("C5", "Q5", 6)),
    ("Q6", _line("C6", "Q6", 2, scoring="holistic")),
    ("Q7", _line("C7", "Q7", 4, scoring="atomic")),
]


def _publish(data_dir: Path, spec: dict):
    store = open_store(data_dir)
    built = build_package(store, spec)
    catalog = PackageCatalog(store.package(built.package_id), package_id=built.package_id,
                             blobs=store.blobs())
    return store, catalog, built.package_version


def test_tc_pkg_39_the_default_decision_table_on_the_published_spec(tmp_data_dir):
    store, catalog, version = _publish(tmp_data_dir, _spec(EXTRA_LINES))
    try:
        stored = {row["criterion_id"]: row["scoring_model"] for row in catalog.criteria(version)}
        observed = [(cid, stored.get(cid), catalog.scoring_model_defaulted(version, cid))
                    for cid, _model, _flag in DECISION_TABLE]
        wrong = [(got, exp) for got, exp in zip(observed, DECISION_TABLE) if got != exp]
        assert not wrong, (
            "the published (criterion, scoring model, default flag) differ from FR-PKG-29's "
            f"table — (got, expected): {wrong}")

        # FR-SETUP-14: the default is a recorded setup step, never indistinguishable from a
        # choice — the row names exactly the lines that took it, with the model each took.
        record = catalog.step_record(version, SCORING_DEFAULT_STEP)
        assert record is not None, "no scoring_model setup-step row was recorded"
        assert record["status"] == "default_taken"
        defaulted = json.loads(record["payload"])["defaulted"]
        for cid, model, flag in DECISION_TABLE:
            if flag:
                assert defaulted.get(cid) == model, (cid, defaulted)
            else:
                assert cid not in defaulted, f"declared line {cid} recorded as defaulted"
    finally:
        store.close()


def test_tc_pkg_39_a_spec_declaring_every_judged_line_records_declared(tmp_data_dir):
    """The flag's other side: when every judged line declares its model, the step row is still
    written (`declared`) and names no defaulted line, so "no default taken" is a recorded fact
    rather than an absent row (FR-SETUP-14)."""
    spec = _spec([("Q6", _line("C6", "Q6", 2, scoring="holistic"))])
    declared = {"C1": "holistic", "C1a": "holistic", "C1b": "atomic", "C2": "atomic",
                "C3": "holistic"}
    for line in spec["criterion"]:
        if line["id"] in declared:
            line["scoring"] = declared[line["id"]]
    store, catalog, version = _publish(tmp_data_dir, spec)
    try:
        stored = {row["criterion_id"]: row["scoring_model"] for row in catalog.criteria(version)}
        for cid, model in {**declared, "C6": "holistic"}.items():
            assert stored[cid] == model, (cid, stored[cid], model)
            assert catalog.scoring_model_defaulted(version, cid) is False, cid
        record = catalog.step_record(version, SCORING_DEFAULT_STEP)
        assert record is not None and record["status"] == "declared", record
        assert json.loads(record["payload"])["defaulted"] == {}
    finally:
        store.close()


def test_tc_pkg_39_the_three_band_row_cannot_be_published(tmp_data_dir):
    """Pins the disclosed substitution: a three-band line is refused at the build (FR-PKG-06),
    so the plan's "three bands → holistic" row has no publishable spec and is asserted on six
    bands above. If this starts passing a build, the row should be restored as written."""
    store = open_store(tmp_data_dir)
    try:
        with pytest.raises(Exception, match=r"odd|2\.\.6"):
            build_package(store, _spec([("Q5", _line("C5", "Q5", 3))]))
    finally:
        store.close()
