"""`TC-PKG-40` (issue #896, CT-PKG-24, RSV-04) — both build paths publish ENG7 with the same
scoring models, and the consumers read them.

Statistical-validity test plan §3.4 (story T3). ENG7 is built twice:

- **CLI arm** — `aeh package build --spec eng7-read-01.package.toml` (`pipeline/packages.py`),
  in process, into its own data directory.
- **Console arm** — the console's authoring path: the shipped draft assembler
  (`aeh.author.spec.assemble` + `render_draft`, via `clarity_world.write_eng7_draft`) writes the
  ENG7 draft into a served console's authoring folder, the approver and the pass boundary are
  answered through the console's own action, and `approve draft package` publishes it.

Expected, per criterion and on **each** arm (absolute, not only equal — restoring the old
`or "holistic"` in `plan_package` would make both arms holistic and keep them equal):
C1a/C1b `atomic`, C2/C3 `holistic`, every one of the four flagged as FR-PKG-29's default. Then,
on the CLI-built package:

- `aggregate`, given the criterion exactly as M-PIPE builds it from the package
  (`pipeline.hooks._criterion_value`), reads `atomic` for C1a: a unanimous but uncited
  three-judge panel scores 1.0 × 0.80 = 0.80, which auto-accepts at the atomic bar (0.80) and
  would have been 0.76 → `queued` had C1a been holistic. C2 under the same panel is holistic
  (0.76, `queued`), so the cell discriminates.
- M-ORCH's base depth for C1a is 1: a real run over the package on a three-judge panel
  enumerates one base score unit per submission for C1a/C1b and three for C2/C3.

**Mutation (run by hand on this branch, recorded in the PR):** `or "holistic"` restored at
`plan_package`'s scoring read → both arms go red on C1a/C1b.

**Plan deviations, disclosed.** (1) The plan names "F-AUTHOR recordings" for the console arm.
No recorded drafting replies exist for ENG7 (`F-AUTHOR/README.md`: AF-22/AF-23 uncaptured), so
the draft is the shipped assembler's own output over the shipped spec's questions and rubric —
the stand-in TC-CONSOLE-89..91 already uses; no recording is hand-written. The console's draft
mints its own criterion ids (`C_Q1_aspect1`, …), mapped below by role. (2) The base depth is read
off a real enumeration, not off the orchestrator's depth map.

**Isolation: rung 3** — real stores, the real console over real HTTP, M-PKG's own build.
**Written ahead of implementation: no** — #864 (PR #922) landed.

Markers. `integration`.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

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
from aeh.agg import aggregate
from aeh.orch import Orchestrator
from aeh.pipeline import cli
from aeh.pipeline.hooks import _criterion_value
from aeh.pkg import PackageCatalog
from aeh.store import open_store
from tests.support.agg_vocabulary import signals, verdict
from tests.support.clarity_world import write_eng7_draft
from tests.support.console_redesign_world import _action, served_console
from tests.support.orch_run import ORCH_COHORT_ID, orch_cfg, seed_cohort

pytestmark = pytest.mark.integration

__all__ = ["served_console"]  # the fixture, imported for pytest

REPO = Path(__file__).resolve().parents[3]
ENG7_SPEC = REPO / "docs" / "live-tests" / "config" / "eng7-read-01.package.toml"
PACKAGE = "ENG7-READ-01"

#: CT-PKG-24's expected models, keyed by the shipped spec's criterion ids.
EXPECTED = {"C1a": "atomic", "C1b": "atomic", "C2": "holistic", "C3": "holistic"}
#: The console draft's ids for the same lines (the assembler mints them per question).
CONSOLE_ID = {"C1a": "C_Q1_aspect1", "C1b": "C_Q1_aspect2", "C2": "C_Q2", "C3": "C_Q3"}
#: FR-SETUP-08's base depth per model, on a three-judge panel.
BASE_DEPTH = {"atomic": 1, "holistic": 3}


def _published(store, package_id: str) -> tuple[PackageCatalog, str]:
    catalog = PackageCatalog(store.package(package_id), package_id=package_id,
                             blobs=store.blobs())
    rows = store.package(package_id).query(
        "SELECT package_version_id FROM package_version WHERE published_at IS NOT NULL")
    assert len(rows) == 1, f"expected one published version of {package_id}, found {rows}"
    return catalog, str(rows[0]["package_version_id"])


def _models(catalog: PackageCatalog, version: str, ids: dict[str, str]) -> dict:
    stored = {str(r["criterion_id"]): r["scoring_model"] for r in catalog.criteria(version)}
    return {cid: (stored.get(ids[cid]), catalog.scoring_model_defaulted(version, ids[cid]))
            for cid in EXPECTED}


def _cli_arm(data_dir: Path, capsys) -> None:
    code = cli.main(["package", "build", "--data-dir", str(data_dir),
                     "--spec", str(ENG7_SPEC)])
    assert code == 0, capsys.readouterr().err


def test_tc_pkg_40_both_build_paths_publish_the_same_scoring_models(
        served_console, tmp_path, capsys) -> None:
    _server, port, console_store, data_dir = served_console

    # Console arm: the shipped assembler's draft, answered and approved through the console.
    draft = write_eng7_draft(data_dir / "authoring", {"pass": None, "not yet": None})
    assert "scoring" not in draft.read_text(encoding="utf-8"), (
        "the console draft declares a scoring model, so it would not exercise the default")
    answered = _action(port, "answer authoring review", {
        "package_id": PACKAGE,
        "answers": [{"item_id": "approved_by", "value": "Dana Teacher"},
                    {"item_id": "grades pass", "value": "6"}]})
    assert answered["refused"] is False, answered
    approved = _action(port, "approve draft package", {"package_id": PACKAGE})
    assert approved["refused"] is False, approved
    catalog, version = _published(console_store, PACKAGE)
    console = _models(catalog, version, CONSOLE_ID)

    # CLI arm: `aeh package build` over the shipped spec, into its own data directory.
    cli_dir = tmp_path / "cli-data"
    cli_dir.mkdir()
    _cli_arm(cli_dir, capsys)
    store = open_store(cli_dir)
    try:
        catalog, version = _published(store, PACKAGE)
        via_cli = _models(catalog, version, {cid: cid for cid in EXPECTED})
    finally:
        store.close()

    expected = {cid: (model, True) for cid, model in EXPECTED.items()}
    assert via_cli == expected, f"CLI build (model, defaulted): {via_cli}"
    assert console == expected, f"console build (model, defaulted): {console}"
    assert via_cli == console


def test_tc_pkg_40_aggregate_and_the_orchestrator_read_the_published_model(
        tmp_path, capsys) -> None:
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    _cli_arm(data_dir, capsys)
    store = open_store(data_dir)
    try:
        catalog, version = _published(store, PACKAGE)
        view = SimpleNamespace(criterion_requires_citation=lambda _cid: True)

        # A unanimous, uncited panel of three on each line's top band: the base is α = 1.0
        # and the uncited multiplier 0.80 — so the scoring model alone decides the routing.
        routed = {}
        for cid in ("C1a", "C2"):
            criterion = _criterion_value(catalog, view, version, cid)
            top = max(criterion.bands, key=lambda b: b["ordinal"])
            panel = [verdict(top["band"], top["ordinal"], cited=False) for _ in range(3)]
            score = aggregate(panel, criterion, signals())
            routed[cid] = (criterion.scoring_model, round(score.confidence, 6), score.routing)
        assert routed["C1a"] == ("atomic", 0.8, "auto"), (
            f"C1a must aggregate as atomic (0.80 meets the atomic bar): {routed['C1a']}")
        assert routed["C2"] == ("holistic", 0.76, "queued"), (
            f"fixture check — C2 is the holistic contrast: {routed['C2']}")

        # FR-SETUP-08 / CT-PKG-24: a real run over the package, a three-judge panel.
        seed_cohort(store, ["S-1", "S-2"])
        orchestrator = Orchestrator(store)
        run_id = orchestrator.create_run(ORCH_COHORT_ID, version, orch_cfg())
        orchestrator.enumerate_units(run_id)
        rows = store.cohort(ORCH_COHORT_ID).query(
            "SELECT criterion_id, submission_id, COUNT(*) AS n FROM work_unit "
            "WHERE run_id = :r AND stage = 'score' GROUP BY criterion_id, submission_id",
            r=run_id)
        depth: dict[str, set[int]] = {}
        for row in rows:
            depth.setdefault(str(row["criterion_id"]), set()).add(int(row["n"]))
        observed = {cid: depth.get(cid) for cid in EXPECTED}
        assert observed == {cid: {BASE_DEPTH[m]} for cid, m in EXPECTED.items()}, (
            f"base score units per submission: {observed}")
    finally:
        store.close()
