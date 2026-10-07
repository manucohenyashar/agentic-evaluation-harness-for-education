"""`TS-144` (issue #621) — `TC-PKG-34`, `TC-PKG-35`, `TC-PKG-36`: the `score_method` vocabulary,
the composite criterion shape, and the `general` type's provenance gate (`FR-PKG-24`,
`FR-PKG-26`, Package migration 15).

Operator-requirements test plan §5.5:

| Case | Input | Expected |
|---|---|---|
| TC-PKG-34 | (a) publish with `score_method='weighted'`; (b) a Package 14 store migrated to 15; (c) criteria with no explicit method | (a) refused, naming `{bands, evidence_sum, general}`; (b) both columns exist (`score_method` default `bands`, `component_of` NULL), the pin is 15, CLAUDE.md names `pkg_criterion_score_method`; (c) every criterion reads `bands` |
| TC-PKG-35 | F-RUBRIC-METHODS publish attempts (a)–(f) | (a) publishes, aspects carry `component_of` = the composite; (b)–(f) each refused naming the violated shape |
| TC-PKG-36 | a `general` criterion with derivation (a) confirmed, (b) pending | (a) publishes, provenance carries the description and the derived band set; (b) refused, naming the criterion |

**Written ahead of #622.** Every test here is `writtenahead`, keyed to #622 in
`WRITTEN_AHEAD_BLOCKERS`. Today they fail on a `TypeError` (the catalog has no `score_method`
argument) or on an assertion that the new columns exist — never on a collection error. The
interface they assume is stated once, in `tests/support/rubric_methods.py`'s docstring.

**Each refusal is one defect away from a fixture that publishes.** `TC-PKG-35(a)` is the positive
control: without it, an implementation that refused every composite would pass every negative.
A refusal is caught as `PackageError` (anything else propagates) and the oracle is twofold — the
message names the offending criterion and the violated shape, and no version locked.

**Isolation: rung 2** — a real store under `tmp_data_dir`; the migration arm builds a raw Package
v14 file exactly as the pre-delta binary left it (the `TC-PKG-31` precedent) and migrates it by
opening a real store over it.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any

import pytest

import aeh.agg  # noqa: F401 — the full migration chain (CLAUDE.md)
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
from aeh.store import (
    COMPLETE_SCHEMA_VERSIONS,
    TIER_MIGRATIONS,
    Tier,
    _SCHEMA_VERSION_TABLE,
    open_store,
)
from tests.support import rubric_methods as rm

pytestmark = pytest.mark.integration

REPO = Path(__file__).resolve().parents[3]

#: Package migration 15 (`FR-PKG-24`, #622): its version and the name CLAUDE.md must carry.
SCORE_METHOD_VERSION = 15
SCORE_METHOD_MIGRATION = "pkg_criterion_score_method"
PRE_DELTA_PACKAGE_VERSION = SCORE_METHOD_VERSION - 1

PACKAGE_ID = "pkg-v14"
VERSION_ID = "pkg-v14@aaaaaaaaaaaa"


@pytest.fixture
def store(tmp_data_dir):
    opened = open_store(tmp_data_dir)
    try:
        yield opened
    finally:
        opened.close()


def _assert_refused(refusal: rm.Refusal, must_name: tuple[str, ...], what: str,
                    closed_set: bool = False) -> None:
    message = str(refusal.error)
    missing = [token for token in must_name if token.lower() not in message.lower()]
    if closed_set:
        missing += rm.names_every_method(message)
    assert not missing, (
        f"{what}: the refusal does not name {missing}. Every refusal names the violated shape "
        f"(TC-PKG-35) and the offending criterion. The message was: {message!r}")
    assert refusal.locked_versions == [], (
        f"{what}: the refusal left locked version(s) {refusal.locked_versions}; a refused "
        "publish is a no-op (CT-PKG-11)")


# --- TC-PKG-34 (b): Package migration 15 -----------------------------------------------------


def test_tc_pkg_34_b_the_package_pin_is_15_and_names_pkg_criterion_score_method():
    """The pin, the chain and CLAUDE.md move together (RISK-119).

    This is also the `WRITTEN_AHEAD_BLOCKERS` key for #622: cheap, and true only when migration
    15 has landed under its design name — another tier-P migration taking 15 would not satisfy
    it.
    """
    chain = {m.version: m.name for m in TIER_MIGRATIONS[Tier.PACKAGE]}
    assert chain.get(SCORE_METHOD_VERSION) == SCORE_METHOD_MIGRATION, (
        f"Package migration {SCORE_METHOD_VERSION} is {chain.get(SCORE_METHOD_VERSION)!r}, not "
        f"{SCORE_METHOD_MIGRATION!r} (FR-PKG-24); the chain is {chain}")
    assert COMPLETE_SCHEMA_VERSIONS[Tier.PACKAGE] == SCORE_METHOD_VERSION, (
        f"COMPLETE_SCHEMA_VERSIONS[Tier.PACKAGE] is {COMPLETE_SCHEMA_VERSIONS[Tier.PACKAGE]}; a "
        "migration added to a chain bumps its pin in the same change (CLAUDE.md, #234)")
    claude_md = (REPO / "CLAUDE.md").read_text(encoding="utf-8")
    assert SCORE_METHOD_MIGRATION in claude_md, (
        "CLAUDE.md's migration-chain paragraph does not name pkg_criterion_score_method: the "
        "paragraph is what tells the next store-opening caller which modules to import")


def _insert(connection: sqlite3.Connection, table: str, values: dict[str, Any]) -> None:
    """`TC-PKG-31`'s `_insert`: by column name, filling any NOT NULL column left out."""
    info = connection.execute(f"PRAGMA table_info({table})").fetchall()
    row = dict(values)
    for _cid, name, col_type, not_null, default, _pk in info:
        if name in row or not not_null or default is not None:
            continue
        numeric = "INT" in (col_type or "").upper() or "REAL" in (col_type or "").upper()
        row[name] = 0 if numeric else f"fixture-{name}"
    names = ", ".join(f'"{c}"' for c in row)
    marks = ", ".join("?" for _ in row)
    connection.execute(f'INSERT INTO "{table}" ({names}) VALUES ({marks})', tuple(row.values()))


def _build_v14_package(data_dir: Path) -> Path:
    """A Package DB standing at version 14, holding one `open` and one `mcq` criterion."""
    path = Path(data_dir) / "packages" / f"{PACKAGE_ID}.pkg.sqlite"
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(path)
    try:
        connection.execute(str(_SCHEMA_VERSION_TABLE))
        for migration in TIER_MIGRATIONS[Tier.PACKAGE]:
            if migration.version > PRE_DELTA_PACKAGE_VERSION:
                continue
            for statement in migration.statements:
                connection.execute(str(statement))
            connection.execute(
                "INSERT INTO schema_version (version, name, applied_at) VALUES (?, ?, ?)",
                (migration.version, migration.name, rm.STAMP))
        _insert(connection, "package", {"package_id": PACKAGE_ID, "created_at": rm.STAMP})
        _insert(connection, "package_version", {
            "package_version_id": VERSION_ID, "package_id": PACKAGE_ID,
            "revision": 1, "locked": 0})
        for criterion_id, kind in (("C-open", "open"), ("C-mcq", "mcq")):
            _insert(connection, "criterion", {
                "package_version_id": VERSION_ID, "criterion_id": criterion_id,
                "kind": kind, "scoring_model": "atomic", "max_points": 1.0})
        connection.commit()
    finally:
        connection.close()
    return path


def test_tc_pkg_34_b_the_v14_fixture_has_neither_column(tmp_data_dir):
    """The fixture's own precondition, so the migration arm cannot pass against a builder that
    created the columns itself."""
    path = _build_v14_package(tmp_data_dir)
    present = set(rm.columns(path, "criterion")) & {"score_method", "component_of"}
    assert present == set(), f"the v14 fixture already carries {sorted(present)}"


def test_tc_pkg_34_b_migration_15_adds_both_columns_with_their_defaults(tmp_data_dir):
    """After opening a real store over the v14 file: `score_method TEXT NOT NULL DEFAULT 'bands'`
    and a nullable `component_of`; every pre-existing criterion reads `bands` / NULL; the file
    records version 15 under the design's name."""
    path = _build_v14_package(tmp_data_dir)
    opened = open_store(tmp_data_dir)
    try:
        opened.package(PACKAGE_ID)
    finally:
        opened.close()

    cols = rm.columns(path, "criterion")
    assert "score_method" in cols and "component_of" in cols, (
        f"after migration criterion has columns {sorted(cols)}; Package 15 adds score_method "
        "and component_of (FR-PKG-24)")
    sm_type, sm_notnull, sm_default = cols["score_method"]
    assert (sm_type.upper(), sm_notnull) == ("TEXT", 1), cols["score_method"]
    assert str(sm_default).strip("'\"") == "bands", (
        f"score_method's default is {sm_default!r}; every criterion that declares no method is "
        "a `bands` criterion (FR-PKG-24)")
    co_type, co_notnull, co_default = cols["component_of"]
    assert (co_type.upper(), co_notnull, co_default) == ("TEXT", 0, None), cols["component_of"]

    stored = rm.criteria_rows(path, VERSION_ID)
    assert {cid: (r["score_method"], r["component_of"]) for cid, r in stored.items()} == {
        "C-open": ("bands", None), "C-mcq": ("bands", None)}

    connection = sqlite3.connect(str(path))
    try:
        applied = dict(connection.execute("SELECT version, name FROM schema_version"))
    finally:
        connection.close()
    assert applied.get(SCORE_METHOD_VERSION) == SCORE_METHOD_MIGRATION, applied


def test_tc_pkg_34_the_column_check_refuses_a_value_outside_the_closed_set(tmp_data_dir):
    """The database backstop: a raw write of `weighted` fails the CHECK, so a widened Python
    vocabulary still cannot store a fourth method."""
    path = _build_v14_package(tmp_data_dir)
    opened = open_store(tmp_data_dir)
    try:
        opened.package(PACKAGE_ID)
    finally:
        opened.close()
    assert "score_method" in rm.columns(path, "criterion"), "Package 15 has not run"

    connection = sqlite3.connect(str(path))
    try:
        with pytest.raises(sqlite3.IntegrityError) as caught:
            _insert(connection, "criterion", {
                "package_version_id": VERSION_ID, "criterion_id": "C-weighted",
                "kind": "open", "scoring_model": "atomic", "max_points": 1.0,
                "score_method": "weighted"})
        assert "CHECK" in str(caught.value).upper(), str(caught.value)
    finally:
        connection.close()


# --- TC-PKG-34 (a) and (c) -------------------------------------------------------------------


def test_tc_pkg_34_a_a_weighted_method_is_refused_naming_the_closed_set(store):
    mutation = next(m for m in rm.MUTATIONS if m.case == "TC-PKG-34a")
    refusal = rm.attempt_build(store, mutation.apply(rm.rubric_methods()))
    _assert_refused(refusal, mutation.must_name, mutation.what, closed_set=True)


def test_tc_pkg_34_c_criteria_with_no_explicit_method_read_bands(store):
    """A package written entirely without the new argument — the pre-#622 call shape, which the
    sample spec's build path still uses — stores `bands` on every criterion."""
    shape = rm.rubric_methods("NO-METHOD")
    shape = rm.without_criteria(shape, rm.GENERAL, rm.COMPOSITE, *rm.ASPECTS)
    shape.questions = shape.questions[:2]
    shape = rm.with_criterion(shape, rm.BANDS, score_method=None)
    assert all(c.score_method is None and c.component_of is None for c in shape.criteria)

    _catalog, version = rm.build(store, shape)

    path = store.package_path(shape.package_id)
    assert "score_method" in rm.columns(path, "criterion"), "Package 15 has not run"
    methods = {cid: r["score_method"] for cid, r in rm.criteria_rows(path, version).items()}
    assert methods == {rm.MCQ: "bands", rm.BANDS: "bands"}, methods


# --- TC-PKG-35 -------------------------------------------------------------------------------


def test_tc_pkg_35_a_a_composite_of_three_two_band_aspects_publishes(store):
    """The positive control: F-RUBRIC-METHODS, unchanged, publishes; each aspect's
    `component_of` is the composite's id; the composite stores no band and `component_of` NULL;
    every row is inside the closed domain."""
    shape = rm.rubric_methods()
    _catalog, version = rm.build(store, shape)

    path = store.package_path(shape.package_id)
    assert rm.locked_versions(path) == [version]
    crit = rm.criteria_rows(path, version)
    assert {a: crit[a]["component_of"] for a in rm.ASPECTS} == {a: rm.COMPOSITE for a in rm.ASPECTS}
    assert crit[rm.COMPOSITE]["score_method"] == "evidence_sum"
    assert crit[rm.COMPOSITE]["component_of"] is None
    assert crit[rm.BANDS]["component_of"] is None and crit[rm.GENERAL]["component_of"] is None
    bands = rm.bands_by_criterion(path, version)
    assert rm.COMPOSITE not in bands, f"the composite carries bands: {bands.get(rm.COMPOSITE)}"
    assert {a: len(bands[a]) for a in rm.ASPECTS} == {a: 2 for a in rm.ASPECTS}
    assert rm.shape_violations(path, version) == []


@pytest.mark.parametrize(
    "mutation", [m for m in rm.MUTATIONS if m.case.startswith("TC-PKG-35")],
    ids=lambda m: m.case)
def test_tc_pkg_35_each_malformed_composite_shape_is_refused_at_publish(store, mutation):
    """(b) a composite with bands, (c) with no aspects, (d) a 3- or 4-band aspect, (e) an aspect
    of a non-composite, (f) a standalone criterion with `component_of` — each refused, naming
    the criterion and the shape it breaks."""
    refusal = rm.attempt_build(store, mutation.apply(rm.rubric_methods()))
    _assert_refused(refusal, mutation.must_name, f"{mutation.case} ({mutation.what})",
                    closed_set=mutation.names_closed_set)


# --- TC-PKG-36 -------------------------------------------------------------------------------


def test_tc_pkg_36_a_a_general_criterion_with_confirmed_derivation_publishes(store):
    """Publishes; the stored provenance carries the teacher's description and the derived band
    set, and the criterion's stored bands ARE that set (the stored form is a bands criterion,
    FR-PKG-26).

    Deliberately silent on what `score_method` the general criterion stores: the CHECK admits
    `general`, while FR-PKG-26 says the stored form "is a `bands` criterion". `shape_violations`
    holds either way, and TC-PKG-37's differential pins whatever #622 chooses.
    """
    shape = rm.rubric_methods()
    catalog, version = rm.build(store, shape)

    path = store.package_path(shape.package_id)
    assert rm.locked_versions(path) == [version]
    expected = rm.band_tuples([vars(b) for b in rm.general_bands()])
    provenance = rm.derivation(catalog, version, rm.GENERAL)
    assert provenance is not None, "no derivation provenance is stored for the general criterion"
    assert provenance["description"] == rm.GENERAL_DESCRIPTION, provenance
    assert rm.band_tuples(provenance["derived_bands"]) == expected, provenance
    stored = rm.band_tuples(rm.bands_by_criterion(path, version)[rm.GENERAL])
    assert stored == expected, (
        f"the general criterion's stored bands {stored} are not its confirmed derived set "
        f"{expected}")
    assert rm.shape_violations(path, version) == []


@pytest.mark.parametrize("state, changes", [
    ("derivation-pending", {"confirm": False}),
    ("no-derivation", {"derive": False, "confirm": False}),
], ids=["derivation-pending", "no-derivation"])
def test_tc_pkg_36_b_a_general_criterion_without_confirmed_derivation_is_refused(
        store, state, changes):
    """Publish refused, naming the criterion (CT-SETUP-17's gate, held at the data layer)."""
    shape = rm.with_criterion(rm.rubric_methods(), rm.GENERAL, **changes)
    refusal = rm.attempt_build(store, shape)
    _assert_refused(refusal, (rm.GENERAL,), f"TC-PKG-36(b) {state}")
