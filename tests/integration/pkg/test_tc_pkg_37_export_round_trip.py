"""`TS-144` (issue #621) — `TC-PKG-37`: the package spec is a system-emitted export that
`aeh package build` accepts unchanged (`FR-PKG-27`, RISK-118, Q-O6).

| Input | Expected |
|---|---|
| F-RUBRIC-METHODS published; `aeh package export --package-version … --spec out.toml`; then `aeh package build --spec out.toml` into a fresh store | the rebuilt package's criteria, bands, points, dependencies and methods equal the original's — a differential over the store rows |
| the shipped sample spec(s) | build unchanged (Q-O6) |

**The differential is over whole rows, not a field list.** Every column of `criterion`, `band`,
`criterion_dependency` and `mcq_option` for the version is compared, keyed by criterion id, with
only `package_version_id` stripped (the rebuilt version has its own id). A hand-picked list
would miss exactly the column an export forgets — the `TC-PKG-31` lesson about copies that
enumerate columns by hand. The `general` criterion's derivation provenance is compared too: #627's
own failure path ("an export of a package containing a `general` criterion round-trips with its
derivation provenance intact").

**Both CLI directions run through `aeh.pipeline.cli.main`**, in process, as the operator types
them.

**Written ahead of #627 (and #622).** The round-trip arms are `writtenahead`, keyed to #627 —
the `export` subcommand does not exist yet, and the fixture itself needs #622's `score_method`.
The sample-spec arm is green today and is NOT marked: it is the regression guard that the build
path keeps accepting the shipped spec while #622/#627 change it.

**Plan finding:** the plan and #627 say "both shipped sample specs"; the repository ships one
(`docs/live-tests/config/ps9-forces-01.package.toml`). The arm builds every tracked
`*.package.toml` and requires at least that one, so a second spec joins automatically.

**Isolation: rung 2** — real stores under `tmp_path`, no network.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

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
from aeh.pipeline import cli
from aeh.store import open_store
from tests.support import rubric_methods as rm

pytestmark = pytest.mark.integration

REPO = Path(__file__).resolve().parents[3]
SAMPLE_SPEC = REPO / "docs" / "live-tests" / "config" / "ps9-forces-01.package.toml"

#: The version-scoped tables the differential compares, and the columns that order their rows.
COMPARED = {
    "criterion": ("criterion_id",),
    "band": ("criterion_id", "ordinal"),
    "criterion_dependency": ("criterion_id", "depends_on"),
    "mcq_option": ("criterion_id", "option_id"),
}


def _shipped_specs() -> list[Path]:
    listed = subprocess.run(
        ["git", "ls-files", "*.package.toml"], cwd=REPO, capture_output=True, text=True,
        check=True).stdout.split()
    specs = sorted({REPO / p for p in listed} | {SAMPLE_SPEC})
    assert SAMPLE_SPEC.exists(), f"the shipped sample spec is gone: {SAMPLE_SPEC}"
    return specs


def _build_from_spec(data_dir: Path, spec: Path, capsys) -> str:
    capsys.readouterr()
    code = cli.main(["package", "build", "--data-dir", str(data_dir), "--spec", str(spec)])
    out = capsys.readouterr()
    assert code == 0, f"`aeh package build --spec {spec.name}` exited {code}: {out.err or out.out}"
    return json.loads(out.out)["package_version"]


def _export(data_dir: Path, version: str, spec: Path, capsys) -> None:
    capsys.readouterr()
    code = cli.main(["package", "export", "--data-dir", str(data_dir),
                     "--package-version", version, "--spec", str(spec)])
    out = capsys.readouterr()
    assert code == 0, f"`aeh package export` exited {code}: {out.err or out.out}"
    assert spec.exists() and spec.stat().st_size > 0, "the export wrote no spec"


def _snapshot(path: Path, version: str) -> dict[str, list[dict]]:
    """Every compared table's rows for `version`, whole, sorted by the table's key.

    Columns ending `_at` are dropped: a rebuild legitimately stamps its own times (if #622
    stores, say, a derivation's `confirmed_at` on the row). Everything else must match."""
    snap = {}
    for table, key in COMPARED.items():
        found = [{k: v for k, v in row.items() if not k.endswith("_at")}
                 for row in rm.rows(path, table, version)]
        snap[table] = sorted(found, key=lambda r: tuple(str(r.get(k)) for k in key))
    return snap


def _package_path(data_dir: Path, package_id: str) -> Path:
    return Path(data_dir) / "packages" / f"{package_id}.pkg.sqlite"


def _diff(original: dict[str, list[dict]], rebuilt: dict[str, list[dict]]) -> list[str]:
    out = []
    for table in COMPARED:
        a, b = original[table], rebuilt[table]
        if a != b:
            only_a = [r for r in a if r not in b]
            only_b = [r for r in b if r not in a]
            out.append(f"{table}: original-only {only_a}; rebuilt-only {only_b}")
    return out


# --- the round trip ----------------------------------------------------------------------------


@pytest.mark.writtenahead
def test_tc_pkg_37_an_exported_spec_rebuilds_the_same_package(tmp_path, capsys):
    """F-RUBRIC-METHODS → export → build into a fresh store → identical rows."""
    source_dir, target_dir = tmp_path / "source", tmp_path / "target"
    shape = rm.rubric_methods("RUBRIC-METHODS")
    store = open_store(source_dir)
    try:
        catalog, version = rm.build(store, shape)
        provenance = rm.derivation(catalog, version, rm.GENERAL)
    finally:
        store.close()
    original = _snapshot(_package_path(source_dir, shape.package_id), version)
    criteria = {r["criterion_id"]: r for r in original["criterion"]}
    # The differential must not pass empty: the original holds every method's line.
    assert {rm.MCQ, rm.BANDS, rm.GENERAL, rm.COMPOSITE, *rm.ASPECTS} <= set(criteria), criteria
    assert criteria[rm.COMPOSITE]["score_method"] == "evidence_sum"
    assert original["criterion_dependency"], "the fixture's dependency edge is missing"
    assert provenance is not None, "the fixture's general derivation is missing"

    spec = tmp_path / "out.toml"
    _export(source_dir, version, spec, capsys)
    rebuilt_version = _build_from_spec(target_dir, spec, capsys)

    assert rebuilt_version.split("@")[0] == shape.package_id, rebuilt_version
    rebuilt_path = _package_path(target_dir, shape.package_id)
    rebuilt = _snapshot(rebuilt_path, rebuilt_version)
    differences = _diff(original, rebuilt)
    assert not differences, (
        "the package rebuilt from its own export differs from the original (FR-PKG-27, "
        "RISK-118):\n  " + "\n  ".join(differences))

    target = open_store(target_dir)
    try:
        round_tripped = rm.derivation(rm.catalog_for(target, shape.package_id),
                                      rebuilt_version, rm.GENERAL)
    finally:
        target.close()
    assert round_tripped is not None, "the general criterion's derivation was lost on export"
    assert round_tripped["description"] == provenance["description"]
    assert rm.band_tuples(round_tripped["derived_bands"]) == rm.band_tuples(
        provenance["derived_bands"])


@pytest.mark.writtenahead
@pytest.mark.parametrize("spec", _shipped_specs(), ids=lambda p: p.name)
def test_tc_pkg_37_a_shipped_sample_round_trips_through_export(tmp_path, capsys, spec):
    """The shipped sample, built, exported and rebuilt, is row-identical to its first build —
    the export is the inverse of build for the specs that exist today, not only for the
    fixture."""
    first_dir, second_dir = tmp_path / "first", tmp_path / "second"
    version = _build_from_spec(first_dir, spec, capsys)
    package_id = version.split("@")[0]
    original = _snapshot(_package_path(first_dir, package_id), version)

    exported = tmp_path / "exported.toml"
    _export(first_dir, version, exported, capsys)
    rebuilt_version = _build_from_spec(second_dir, exported, capsys)
    differences = _diff(original, _snapshot(_package_path(second_dir, package_id),
                                            rebuilt_version))
    assert not differences, "\n  ".join(differences)


# --- Q-O6: the shipped specs still build -------------------------------------------------------


@pytest.mark.parametrize("spec", _shipped_specs(), ids=lambda p: p.name)
def test_tc_pkg_37_every_shipped_sample_spec_still_builds(tmp_path, capsys, spec):
    """Q-O6: `aeh package build --spec` stays, and the shipped specs build unchanged. Green
    today; the guard that #622/#627's changes to the build path keep accepting them."""
    version = _build_from_spec(tmp_path / "data", spec, capsys)
    package_id = version.split("@")[0]
    path = _package_path(tmp_path / "data", package_id)
    assert rm.locked_versions(path) == [version], "the sample built but did not publish"
    assert rm.rows(path, "criterion", version), "the sample built with no criteria"
