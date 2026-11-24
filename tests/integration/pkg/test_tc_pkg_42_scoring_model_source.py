"""`TC-PKG-42` (issue #904; FR-PKG-30, CT-PKG-25, Package migration P3): every published
criterion records who chose its scoring model, and M-PKG itself refuses a judged band with no
descriptor.

Statistical validity test plan r2 §3.21, story T20.

| Arm | Expected |
|---|---|
| sources | the console's approve action over a draft whose Q3 line declares `scoring`, carrying the teacher's choice for Q2: Q3 `declared`, Q2 `teacher` (its model the teacher's, `scoring_model_confirmed_at` set), every other judged line `default`; only `teacher` has a confirmation time; the published rows refuse an update (`criterion_immutable`) |
| M-PKG refusal | a version written straight through `PackageCatalog` — no authoring gate on the path — with one judged band's descriptor empty is refused at publish, naming the criterion and band, and nothing locks; its positive controls publish: the valid shape, an aspect's `absent` band empty, the multiple-choice `incorrect`/`correct` bands empty |
| P3 upgrade | a Package v18 file (precondition: neither column) opened by a real store: the old row reads `declared` with no confirmation time, through the file and through the catalog; the CHECK refuses `other` and accepts a `teacher` twin of the same shape |
| pin, F-SCHEMA | migration 19 is `pkg_criterion_scoring_model_source` and the Package pin is the chain head; every `package@vN` golden entry's `criterion` carries both columns, `package@v19` among them |

**The draft** is `tests.support.descriptor_world`'s plain-bands draft (the shipped assembler's
over the ENG7 inventory), its descriptors answered on the console, so approval reaches M-PKG.

**No clock seam on the publish path**, so `scoring_model_confirmed_at` is checked as an ISO
time inside the approve call's window, not as a literal.

**Isolation: rung 3** — a real store, the real console over HTTP, M-PKG's own build; the upgrade
arm builds a raw Package v18 file from the tier's own declared migrations
(`tests/support/tier_at_version.py`) and opens a real store over it.
**Written ahead of implementation: no, in effect.** The issue says `yes`, but #876 is merged,
so every arm passes and none carries `writtenahead`.

Markers. `integration`.
"""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
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
from aeh.store import COMPLETE_SCHEMA_VERSIONS, TIER_MIGRATIONS, Tier, open_store
from tests.support import rubric_methods as rm
from tests.support.console_redesign_world import _action, draft_read, served_console
from tests.support.descriptor_world import APPROVER, PACKAGE, PLAIN_BANDS, \
    write_plain_bands_draft
from tests.support.tier_at_version import (
    STAMP,
    build_tier_at,
    columns,
    insert_row,
    rows,
    schema_version,
    tier_path,
    try_insert,
)

pytestmark = pytest.mark.integration

__all__ = ["served_console"]  # the fixture, imported for pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
F_SCHEMA = REPO_ROOT / "fixtures" / "F-SCHEMA" / "post-migration-checksums.json"

#: Migration P3: (tier, version, name).
P3 = (Tier.PACKAGE, 19, "pkg_criterion_scoring_model_source")
NEW_COLUMNS = ("scoring_model_source", "scoring_model_confirmed_at")

UPGRADE_PACKAGE = "pkg-t20"
UPGRADE_VERSION = "pkg-t20@aaaaaaaaaaaa"


def _criterion_rows(path: Path) -> dict[str, dict]:
    (version,) = rm.locked_versions(path)
    return rm.criteria_rows(path, version)


# --- the three sources, through the approve action ------------------------------------------


def test_tc_pkg_42_declared_default_and_teacher_through_the_approve_action(
        served_console) -> None:
    _server, port, store, data_dir = served_console
    write_plain_bands_draft(data_dir / "authoring", declare_q3="holistic")
    _action(port, "answer authoring review", {"package_id": PACKAGE, "answers": [
        {"item_id": "approved_by", "value": APPROVER},
        *({"item_id": f"descriptor {band} Q2", "value": f"Shows the {band} reasoning."}
          for band, _points in PLAIN_BANDS)]})

    criteria = {c["id"]: c for c in draft_read(port)["draft"]["criteria"]}
    asked = sorted(cid for cid, c in criteria.items() if c.get("confirm") == "ask")
    # The declared line is not offered; Q2's defaulted four-band line is.
    assert "C_Q3" not in asked and "C_Q2" in asked, asked
    assert criteria["C_Q2"].get("chosen_automatically") is True, criteria["C_Q2"]

    before = datetime.now(timezone.utc)
    approved = _action(port, "approve draft package",
                       {"package_id": PACKAGE, "scoring": {"C_Q2": "atomic"}})
    after = datetime.now(timezone.utc)
    assert approved["refused"] is False, approved

    path = store.package_path(PACKAGE)
    stored = _criterion_rows(path)
    sources = {cid: row["scoring_model_source"] for cid, row in stored.items()}
    assert sources.pop("C_Q3") == "declared"
    assert sources.pop("C_Q2") == "teacher"
    assert sources.pop("C_Q4_key") == "declared", "a keyed line's model is not defaulted"
    assert sources and set(sources.values()) == {"default"}, (
        f"every other judged line took FR-PKG-29's default: {sources}")

    assert stored["C_Q3"]["scoring_model"] == "holistic"
    assert stored["C_Q2"]["scoring_model"] == "atomic", "the teacher's choice is the model"
    confirmed = datetime.fromisoformat(stored["C_Q2"]["scoring_model_confirmed_at"])
    assert before <= confirmed <= after, confirmed
    for cid, row in stored.items():
        if cid != "C_Q2":
            assert row["scoring_model_confirmed_at"] is None, (cid, row)

    # The catalog's own reads agree with the file.
    catalog = rm.catalog_for(store, PACKAGE)
    (version,) = rm.locked_versions(path)
    for cid, row in stored.items():
        assert catalog.scoring_model_source(version, cid) == row["scoring_model_source"], cid
        assert catalog.scoring_model_confirmed_at(version, cid) == \
            row["scoring_model_confirmed_at"], cid

    # Published rows are immutable: the source cannot be rewritten after publication.
    connection = sqlite3.connect(path)
    try:
        with pytest.raises(sqlite3.IntegrityError, match="immutable"):
            connection.execute(
                "UPDATE criterion SET scoring_model_source = 'declared', "
                "scoring_model_confirmed_at = NULL WHERE criterion_id = 'C_Q2'")
    finally:
        connection.close()


# --- M-PKG's own descriptor refusal (CT-PKG-25), independent of the authoring gate ----------


@pytest.fixture
def store(tmp_data_dir):
    opened = open_store(tmp_data_dir)
    try:
        yield opened
    finally:
        opened.close()


def _emptied(shape: rm.PackageShape, criterion_id: str, band: str) -> rm.PackageShape:
    (criterion,) = [c for c in shape.criteria if c.criterion_id == criterion_id]
    bands = [rm.Band(b.ordinal, b.band, b.points, "" if b.band == band else b.descriptor)
             for b in criterion.bands]
    assert any(b.band == band for b in bands), (criterion_id, band)
    return rm.with_criterion(shape, criterion_id, bands=bands)


def test_tc_pkg_42_m_pkg_refuses_a_judged_band_with_an_empty_descriptor(store) -> None:
    refusal = rm.attempt_build(store, _emptied(rm.rubric_methods("DESC-EMPTY"), rm.BANDS,
                                               "limited"))
    message = str(refusal.error)
    assert repr(rm.BANDS) in message and "'limited'" in message, message
    assert "descriptor" in message, message
    assert refusal.locked_versions == [], "a refused publish locked a version"


def test_tc_pkg_42_m_pkg_descriptor_check_exemptions_publish(store) -> None:
    valid = rm.rubric_methods("DESC-VALID")
    # The valid shape's multiple-choice line already carries `incorrect`/`correct` with no
    # descriptor: its publishing is the keyed-line exemption's positive control.
    (key_line,) = [c for c in valid.criteria if c.criterion_id == rm.MCQ]
    assert {b.band for b in key_line.bands} == {"incorrect", "correct"}
    assert all(not b.descriptor for b in key_line.bands), "the key line's bands carry text"
    shapes = {
        "DESC-VALID": valid,
        "DESC-ABSENT": _emptied(rm.rubric_methods("DESC-ABSENT"), rm.ASPECTS[0], "absent"),
    }
    for package_id, shape in shapes.items():
        _catalog, version = rm.build(store, shape)
        assert rm.locked_versions(store.package_path(package_id)) == [version], package_id


# --- migration P3: the upgrade, the CHECK, the pin and the golden ---------------------------


def _seed_v18(connection: sqlite3.Connection) -> None:
    insert_row(connection, "package", {"package_id": UPGRADE_PACKAGE, "created_at": STAMP})
    insert_row(connection, "package_version", {
        "package_version_id": UPGRADE_VERSION, "package_id": UPGRADE_PACKAGE, "revision": 1,
        "locked": 0})
    insert_row(connection, "criterion", {
        "package_version_id": UPGRADE_VERSION, "criterion_id": "C-old", "question_id": "Q1",
        "kind": "open", "max_points": 3.0, "scoring_model": "holistic"})


def _v18_file(data_dir: Path) -> Path:
    path = build_tier_at(tier_path(data_dir, Tier.PACKAGE, UPGRADE_PACKAGE), Tier.PACKAGE,
                         P3[1] - 1, _seed_v18)
    assert schema_version(path) == P3[1] - 1
    return path


def test_tc_pkg_42_precondition_neither_column_at_package_18(tmp_data_dir) -> None:
    present = columns(_v18_file(tmp_data_dir), "criterion")
    assert present and not set(NEW_COLUMNS) & set(present), sorted(present)


def test_tc_pkg_42_p3_upgrade_old_rows_read_declared_and_the_check_holds(tmp_data_dir) -> None:
    path = _v18_file(tmp_data_dir)
    opened = open_store(tmp_data_dir)
    try:
        catalog = rm.catalog_for(opened, UPGRADE_PACKAGE)
        assert catalog.scoring_model_source(UPGRADE_VERSION, "C-old") == "declared"
        assert catalog.scoring_model_confirmed_at(UPGRADE_VERSION, "C-old") is None
    finally:
        opened.close()
    assert schema_version(path) == COMPLETE_SCHEMA_VERSIONS[Tier.PACKAGE]

    (old,) = rows(path, "SELECT * FROM criterion WHERE criterion_id = 'C-old'")
    assert old["scoring_model_source"] == "declared", old
    assert old["scoring_model_confirmed_at"] is None, old

    shape = {"package_version_id": UPGRADE_VERSION, "question_id": "Q1", "kind": "open",
             "max_points": 3.0, "scoring_model": "holistic"}
    accepted = try_insert(path, "criterion", {
        **shape, "criterion_id": "C-teacher", "scoring_model_source": "teacher",
        "scoring_model_confirmed_at": STAMP})
    assert accepted is None, f"a 'teacher' row was refused: {accepted}"
    refused = try_insert(path, "criterion", {
        **shape, "criterion_id": "C-other", "scoring_model_source": "other"})
    assert refused is not None and "CHECK" in str(refused).upper(), (
        f"scoring_model_source='other' was not refused by the CHECK: {refused}")
    assert {r["criterion_id"] for r in rows(path, "SELECT criterion_id FROM criterion")} == {
        "C-old", "C-teacher"}


def test_tc_pkg_42_the_package_pin_and_the_f_schema_golden() -> None:
    tier, version, name = P3
    chain = {m.version: m.name for m in TIER_MIGRATIONS[tier]}
    assert chain.get(version) == name, (
        f"Package migration {version} is {chain.get(version)!r}, not {name!r}")
    assert COMPLETE_SCHEMA_VERSIONS[tier] == max(chain) >= version, (
        f"the Package pin is {COMPLETE_SCHEMA_VERSIONS[tier]}, the chain head {max(chain)}")

    golden = json.loads(F_SCHEMA.read_text(encoding="utf-8"))
    entries = {k: v for k, v in golden.items() if k.startswith("package@v")}
    assert f"package@v{version}" in entries, sorted(entries)
    for key, tables in entries.items():
        assert set(NEW_COLUMNS) <= set(tables["criterion"]["columns"]), key
