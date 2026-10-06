"""`TS-147` (issue #628) — `TC-CONSOLE-C30`, `CT-CONSOLE-30` (v2.0) as the provider's clause
suite: *the API under `/api/` and the SPA under `/` are served from one origin with zero external
requests; the API's mutations are exactly the enumerated control writes.*

**Breaks if** a mutation appears in the API that no enumerated control row backs, or an external
origin enters any served byte. Operator-requirements test plan §5.6 / §6.11: TC-CONSOLE-53 (b)–(c)
run as the clause suite, so this file asserts the clause in its two "breaks if" forms and leaves
the per-route dispatch, unlisted-path and read-route write audits to
`tests/integration/console/test_tc_console_53_api_one_origin.py`.

Two halves, as in TS-76's console suites:

* **The controls (green today).** The census and the sweep are this suite's instruments, and an
  instrument that cannot see the violation passes every console. So each is run against the
  violation it exists for — a route table carrying an orphan mutation, a bundle carrying an
  external origin in each place RISK-108 names — and against the honest version, which must pass.
  These need no implementation and run in `TEST_CMD`.
* **The clause (written ahead of #629).** The real `API_ROUTES` has no orphan; a planted bundle
  served by the real server over the loopback bind is caught in every served byte that carries an
  origin, and the clean bundle served the same way is not — the differential that shows the
  server's own bytes, not just the fixture's, went through the sweep.

Rung 2: a real `serve_console` on loopback, the network guard loosened for loopback only.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

import aeh.agg  # noqa: F401 — the full migration chain before any store open (CLAUDE.md)
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
from aeh.store import open_store
from tests.support.console_api_vocabulary import (
    API_ISSUE,
    CLEAN_BUNDLE,
    NON_CONTROL_MUTATIONS,
    PLANTED_ORIGINS,
    ROUTE_TABLE,
    concrete_path,
    crawl_spa,
    external_references,
    fetch,
    mutating_rows,
    on_loopback,
    orphan_mutations,
    planted_bundle,
    route_rows,
    start_console,
    write_bundle,
)
from tests.support.impl import CONSOLE_MODULE, require

pytestmark = pytest.mark.contract

#: The fifteen, spelled as the clause suite's double needs them — read from the module in the
#: clause cases; here only to build synthetic tables for the controls.
_TWO_CONTROLS = ("start run", "pause/resume")


def _route(method: str, path: str, control):
    return SimpleNamespace(method=method, path=path, control=control)


def _sweep(responses) -> dict[str, list[str]]:
    return {
        path: refs for path, (_status, headers, body) in responses.items()
        if (refs := external_references(body, headers.get("content-type", "")))
    }


# --- the controls: the instruments see what they exist to see --------------------------------


def test_tc_console_c30_control_the_census_reports_an_orphan_mutation_and_passes_a_clean_table():
    clean = [
        _route("GET", "/api/v1/runs/{id}", None),
        _route("POST", "/api/v1/runs/{id}/start", "start run"),
        _route("POST", "/api/v1/runs/{id}/pause", "pause/resume"),
        _route("POST", "/api/v1/uploads", "upload scans"),
    ]
    orphaned = clean + [
        _route("DELETE", "/api/v1/grades/{id}", "delete grade"),
        _route("PATCH", "/api/v1/runs/{id}", None),
    ]

    assert orphan_mutations(clean, _TWO_CONTROLS) == []
    assert orphan_mutations(orphaned, _TWO_CONTROLS) == [
        ("DELETE", "/api/v1/grades/{id}", "delete grade"),
        ("PATCH", "/api/v1/runs/{id}", None),
    ], "a mutation with no enumerated control row — named or unlabelled — must be an orphan"
    smuggled = clean + [
        _route("POST", "/api/v1/cohorts", "upload scans"),
        _route("DELETE", "/api/v1/cohorts/{id}", "upload scans"),
    ]
    assert orphan_mutations(smuggled, _TWO_CONTROLS) == [
        ("POST", "/api/v1/cohorts", "upload scans"),
        ("DELETE", "/api/v1/cohorts/{id}", "upload scans"),
    ], "the upload exception admits one POST route; a second route wearing its label is an orphan"
    assert set(NON_CONTROL_MUTATIONS) == {"upload scans"}, (
        "the census admits exactly one named non-control mutation (FR-CONSOLE-04's upload); a "
        "second is a design decision, not an edit to this test"
    )


def test_tc_console_c30_control_the_sweep_flags_every_planted_origin_and_passes_the_clean_bundle():
    clean = {name: external_references(data, "text/html" if name.endswith(".html") else "")
             for name, data in CLEAN_BUNDLE.items()}
    planted = planted_bundle()
    found = [ref for name, data in planted.items()
             for ref in external_references(data, "text/html" if name.endswith(".html") else "")]

    assert all(refs == [] for refs in clean.values()), (
        f"the sweep condemns an honest bundle: {clean} — the SVG namespace is an identifier, "
        "a root-relative asset is this origin, a `//` comment in JS is not a URL"
    )
    assert sorted(found) == sorted(PLANTED_ORIGINS.values()), (
        f"the sweep found {found} of the planted {sorted(PLANTED_ORIGINS.values())}"
    )
    assert external_references(b'{"next":"https:\\/\\/evil.example\\/x"}') != [], (
        "a JSON-escaped URL in an API response is still an external origin"
    )
    assert external_references(b'{"self":"http://127.0.0.1:8765/api/v1/runs"}') == []


# --- the clause (written ahead of #629) ------------------------------------------------------


@pytest.mark.writtenahead
def test_tc_console_c30_the_api_mutations_are_exactly_the_enumerated_control_writes():
    """Breaks if a mutation appears in the API that no enumerated control row backs."""
    routes = list(require(CONSOLE_MODULE, ROUTE_TABLE, issue=API_ISSUE))
    CONTROL_SURFACE_ACTIONS = require(CONSOLE_MODULE, "CONTROL_SURFACE_ACTIONS")

    assert mutating_rows(routes), (
        f"{ROUTE_TABLE} lists no mutation: the clause holds vacuously of an API with no control "
        "surface, which is not the API FR-CONSOLE-45 describes"
    )
    orphans = orphan_mutations(routes, CONTROL_SURFACE_ACTIONS)
    census = "\n".join(f"  {m:6} {p:48} -> {c}" for m, p, c in route_rows(routes))
    assert orphans == [], (
        f"CT-CONSOLE-30 broken — API mutations no enumerated control row backs: {orphans}\n"
        f"census:\n{census}"
    )


@pytest.mark.writtenahead
@pytest.mark.integration
def test_tc_console_c30_an_external_origin_in_any_served_byte_breaks_the_clause(
    tmp_data_dir, tmp_path, network_guard, monkeypatch
):
    """The same server over a planted and a clean bundle: every planted origin is found in what
    the server sent, and nothing is found in the clean one or in the API's answers."""
    serve, routes = require(CONSOLE_MODULE, "serve_console", ROUTE_TABLE, issue=API_ISSUE)
    for name in ("HARNESS_PROFILE", "CONSOLE_BIND", "CONSOLE_PORT"):
        monkeypatch.delenv(name, raising=False)
    store = open_store(tmp_data_dir)
    try:
        sent = {}
        for label, bundle in (("planted", planted_bundle()), ("clean", CLEAN_BUNDLE)):
            server = start_console(serve, store, spa_dir=write_bundle(tmp_path / label, bundle))
            with on_loopback(server, network_guard) as (port, _census):
                served, leaving = crawl_spa(port)
                assert not leaving, f"a redirect left the origin: {leaving}"
                if label == "clean":
                    for method, path, _control in route_rows(routes):
                        if method == "GET":
                            served[f"GET {path}"] = fetch(port, "GET", concrete_path(path))
            sent[label] = served
    finally:
        store.close()

    planted_found = sorted({ref for refs in _sweep(sent["planted"]).values() for ref in refs})
    assert planted_found == sorted(PLANTED_ORIGINS.values()), (
        f"the server sent a planted bundle and the sweep of its bytes found {planted_found}, not "
        f"every planted origin {sorted(PLANTED_ORIGINS.values())}: either a file was not served "
        "or the sweep did not read it"
    )
    assert _sweep(sent["clean"]) == {}, (
        f"CT-CONSOLE-30 broken — the console sent external origins: {_sweep(sent['clean'])}"
    )
    network_guard.assert_no_network()
