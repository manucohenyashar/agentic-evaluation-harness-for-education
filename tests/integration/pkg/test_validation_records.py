"""Validation records keyed by population, `NoValidationData`, and the manifest (`M-PKG`).

Cases `TC-PKG-15`, `TC-PKG-16`, `TC-PKG-17`, `TC-PKG-18`, `TC-PKG-26` (`FR-PKG-08`,
`-09`, `-12`, `-21`), test plan §5.4. Issue #29.

Rung 2 — real Tier P files: the `NoValidationData` oracle is a **type** assertion, and
the manifest's no-aggregate guarantee is an artifact assertion over its fields.

`Written ahead of implementation: yes` is stale — the validation surface landed with #29;
the cases run green by design.
"""

from __future__ import annotations

import pytest

from aeh.pkg import (
    Manifest,
    NoValidationData,
    PackageCatalog,
    PackageDraft,
)
from aeh.store import open_store
from tests.support.store_api import statement

pytestmark = pytest.mark.integration

ISSUE = "#29"


def _catalog(tmp_data_dir):
    store = open_store(tmp_data_dir)
    handle = store.package("pkg-29")
    with handle.transaction() as tx:
        tx.execute(statement(
            "INSERT INTO package (package_id, created_at) "
            "VALUES ('pkg-29', '2026-01-01')", issue=ISSUE), p="pkg-29")
    catalog = PackageCatalog(handle, package_id="pkg-29")
    v = catalog.create_version(None, PackageDraft(title="validation target"))
    catalog.add_criterion(v, "CRIT-1", question_id="Q-1", kind="open", max_points=4.0,
                          band_count=2)
    catalog.add_band(v, "CRIT-1", 0, "b0", 0.0)
    catalog.add_band(v, "CRIT-1", 1, "b1", 1.0)
    return store, handle, catalog, v


def test_tc_pkg_15_validation_records_are_keyed_per_population(tmp_data_dir):
    """`TC-PKG-15` — *'the key is (package_version_id, criterion_id, population_scope_id,
    backend_profile, panel_build_ref, scoring_model)'* — two populations with identical
    backend/panel figures store as TWO rows, and neither answers for the other."""
    store, handle, catalog, v = _catalog(tmp_data_dir)
    catalog.store_validation(v, "CRIT-1", "pop-7a", "ollama-local", "panel@2024", "atomic",
                             0.82, 40)
    catalog.store_validation(v, "CRIT-1", "pop-7b", "ollama-local", "panel@2024", "atomic",
                             0.64, 35)
    a = catalog.validation_for(v, "pop-7a", "ollama-local", "panel@2024", "atomic")
    b = catalog.validation_for(v, "pop-7b", "ollama-local", "panel@2024", "atomic")
    assert not isinstance(a, NoValidationData) and a["agreement"] == 0.82
    assert not isinstance(b, NoValidationData) and b["agreement"] == 0.64
    store.close()


def test_tc_pkg_16_no_headline_figure_exists_on_the_surface(tmp_data_dir):
    """`TC-PKG-16` — *'no query returns a package-level or criterion-level "validated"
    boolean or a single headline figure across populations.'* Oracle: **artifact
    assertion** — the catalog's public methods contain no aggregate; the manifest carries
    per-population entries only."""
    store, handle, catalog, v = _catalog(tmp_data_dir)
    forbidden = ("validated", "headline", "overall_agreement", "average_agreement",
                 "mean_agreement", "aggregate")
    public = [name for name in dir(catalog) if not name.startswith("_")]
    for name in public:
        for word in forbidden:
            assert word not in name.lower(), (
                f"TC-PKG-16: the catalog surface exposes {name!r}. A package-level or "
                "cross-population validated figure repeats HLD §2.1's error (R23) — the "
                "surface answers keys, never aggregates."
            )
    # The manifest's fields, likewise: no aggregate field exists to render.
    manifest_fields = set(Manifest.__dataclass_fields__)
    assert not (manifest_fields & {w for w in forbidden}), (
        f"TC-PKG-16: the Manifest carries an aggregate field: "
        f"{sorted(manifest_fields & set(forbidden))}. FR-PKG-21: per-population entries "
        "only."
    )
    store.close()


def test_tc_pkg_17_a_missing_key_returns_novalidationdata_in_type(tmp_data_dir):
    """`TC-PKG-17` — *'validation_for for a key with no matching row returns an explicit
    NoValidationData result distinguishable in type from a zero or a low figure.'*

    Oracle: **type assertion** — `result is NoValidationData()`; a test asserting
    `result == 0` would pass against the bug the requirement exists to prevent."""
    store, handle, catalog, v = _catalog(tmp_data_dir)
    result = catalog.validation_for(v, "pop-absent", "backend", "panel", "atomic")
    assert isinstance(result, NoValidationData), (
        f"TC-PKG-17: an absent key returned {type(result).__name__}. The oracle is the "
        "TYPE — never zero, never null, never a figure from an adjacent key (CT-PKG-07)."
    )
    assert result is NoValidationData()
    # An adjacent key's figure must not leak either:
    catalog.store_validation(v, "CRIT-1", "pop-real", "ollama-local", "panel@2024",
                             "atomic", 0.9, 50)
    adjacent = catalog.validation_for(v, "pop-other", "ollama-local", "panel@2024",
                                      "atomic")
    assert isinstance(adjacent, NoValidationData)
    store.close()


def test_tc_pkg_18_the_manifest_carries_per_population_entries_and_the_weakest(
    tmp_data_dir,
):
    """`TC-PKG-26` — *'the manifest contains per-population validation entries, the
    weakest criterion per population, exemplar provenance and schema version — and no
    field aggregating validation across populations.'*

    The weakest flag travels deliberately (`FR-STATS-13`): a package advertising only
    its overall number is the portable form of the §2.1 error."""
    store, handle, catalog, v = _catalog(tmp_data_dir)
    catalog.store_validation(v, "CRIT-1", "pop-a", "backend", "panel", "atomic", 0.9, 30)
    catalog.store_validation(v, "CRIT-1", "pop-b", "backend", "panel", "atomic", 0.55, 30)
    manifest = catalog.manifest(v)
    assert isinstance(manifest, Manifest)
    assert manifest.schema_version >= 1
    assert {e.population_scope_id for e in manifest.entries} == {"pop-a", "pop-b"}
    weakest = [e for e in manifest.entries if e.is_weakest]
    # One weakest PER population: each population's lowest-agreement entry carries the
    # flag, so the manifest says which criterion is the weak one in each population —
    # never an aggregate across them.
    assert {e.population_scope_id for e in weakest} == {"pop-a", "pop-b"}, (
        "TC-PKG-26: the manifest does not flag the weakest criterion per population. "
        "FR-STATS-13 makes it travel deliberately — a package advertising only its "
        "overall number is the portable form of the §2.1 error."
    )
    pop_b_weakest = next(e for e in weakest if e.population_scope_id == "pop-b")
    assert pop_b_weakest.agreement == 0.55
    store.close()
