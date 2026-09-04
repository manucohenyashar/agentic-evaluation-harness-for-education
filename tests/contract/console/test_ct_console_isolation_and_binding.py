"""`CT-CONSOLE-04`, `-05` and `-06` — the three security clauses, and the three things a console
must be unable to do.

Test plan §6.11.19, TS-76 (issue #131). These are the clauses whose violation has no symptom.

* `-04` — no path from the UI into a judgment. `R15`'s contamination channel produces grades that
  look exactly like correct ones; the only way to see it is structurally, as a set operation.
* `-05` — loopback only, and a refusal to start under `cloud-hosted`. RISK-20 is *"an
  unauthenticated student-record system on a school LAN"*, and design §3.19 says why the refusal is
  code rather than documentation.
* `-06` — nothing about a student on the machine, nothing on the network. HLD §11.7's reason for
  the second half is not privacy alone: *"a CDN reference is a console that renders blank at a
  school with no internet — the deployment this system exists for"*.

Keyed on **#124** (`-04`, `-06`, which are `FR-CONSOLE-03/17/18`) and **#122** (`-05`,
`FR-CONSOLE-05`). Every name is invented; the surface is settled in
`tests/support/console_vocabulary.py` and `tests/support/console_security_vocabulary.py`.

Two things this file does not do, both reported on the PR rather than faked
--------------------------------------------------------------------------
**`CT-CONSOLE-04` is asserted phase-scoped, not literally.** Read literally — *"writes no field
that any scoring prompt reads"* — the clause is unsatisfiable against HLD §11.8's own control
surface, which writes `criterion.text` and `criterion_band.descriptor`. The scoping is the HLD's,
not this suite's, and `test_the_literal_clause_is_unsatisfiable_and_the_hld_scopes_it` in the
vocabulary file asserts both halves of that reasoning.

**`CT-CONSOLE-06`'s storage half is narrower than §6.11.19's instrument.** The plan describes *"a
single Playwright load"*, but §4.5's environment table assigns the three browser-level facts to
`TC-CONSOLE-40..42` — which are **TS-49's**, under E6 — and §4.10 budgets this tier at 60 seconds
with no browser. So what is asserted here is what is assertable from served output: no storage API
reached from the markup, and no external origin referenced at all. For the origin half that is
arguably stronger than a page load, since a CDN reference the browser happens not to fetch is still
there. For the storage half it is narrower, and the PR says so.
"""

from __future__ import annotations

import itertools

import pytest

from tests.support import broken_console_security_fixtures as fixtures
from tests.support.conf_builders import hosted_cfg
from tests.support.console_security_vocabulary import (
    CLOUD_HOSTED_PROFILE,
    LOOPBACK_ADDRESSES,
    REFUSAL_SWEEP_SETTINGS,
    SCORING_PROMPT_FIELDS,
    browser_storage_writes,
    external_origins,
    post_lock_write_fields,
    prompt_visible_writes,
)
from tests.support.impl import CONSOLE_MODULE, require
from tests.support.store_spy import StoreSpy

pytestmark = pytest.mark.contract


# --- CT-CONSOLE-04 — no path from the UI into a judgment -----------------------------------------


@pytest.mark.writtenahead
def test_tc_console_c04_no_field_the_console_writes_after_the_lock_is_read_by_a_scoring_prompt():
    """`CT-CONSOLE-04` / `FR-CONSOLE-03` — the empty intersection, computed against the **running**
    console rather than against the fixture.

    §6.11.19 says this is *"stronger than sampling prompts"*, and the strength comes from both
    sides being complete: `SCORING_PROMPT_FIELDS` is HLD §9.9's closed whitelist, and the write set
    is `FR-CONSOLE-32`'s runtime enumeration. Sampling a few prompts finds a contamination channel
    only if it happens to sample the prompt that has one.

    **Scoped to post-lock writes, and the scope is the HLD's.** §11.1: *"nothing it writes is
    visible to a judge at inference time … teacher review actions are written after scoring"*;
    §11.8 bounds the rubric read-back to *"before any scoring exists, inside the §6.2 lock"*. The
    unscoped reading is unsatisfiable against §11.8's own table, and a test written to it goes red
    against a compliant console — the failure review found three times in TS-77.

    The non-vacuity anchor is asserted first: `criterion.answer_key` is a genuine post-lock write
    that is correctly disjoint, so an empty intersection means "disjoint" rather than "nothing was
    written".
    """
    build_console = require(CONSOLE_MODULE, "build_console", issue="#124")

    app = build_console(store=StoreSpy())
    written = post_lock_write_fields(
        {action: tuple(app.write_fields(action)) for action in app.write_surface()}
    )

    assert written, (
        "the console's runtime write map is empty after the §6.2 lock, so the intersection below "
        "is empty for free. Eleven of the fifteen control actions are post-lock — 'correct an "
        "answer key after a run' among them."
    )
    assert "criterion.answer_key" in written, (
        f"the post-lock write set is {sorted(written)} and does not include criterion.answer_key. "
        f"That write is the anchor: a real post-lock write that touches a criterion and is still "
        f"correctly disjoint from everything a prompt reads."
    )
    # **Translated before it is intersected.** §11.8's Effect column names store fields
    # (`criterion_band.descriptor`) and §9.9 names JSON paths (`criterion.bands.descriptor`), so a
    # raw set intersection across the two is a string coincidence rather than a comparison — it
    # would report nothing however contaminated the write surface was, except under `criterion.*`
    # where the two spellings happen to agree. Review measured that.
    visible = prompt_visible_writes(written)
    assert not visible, (
        f"the console writes these after the §6.2 lock and a scoring prompt reads them: "
        f"{sorted(f'{store} (read as {leaf})' for store, leaf in visible.items())}. That is R15's "
        f"contamination channel reopened at the UI — a field a later judgment picks up, which is "
        f"what §9.1's one-way rule forbids."
    )


@pytest.mark.writtenahead
def test_tc_console_c04_no_per_student_annotation_surface_exists_on_any_route():
    """The clause's second half, and the one that would arrive as a feature request.

    *"Exposes no per-student annotation surface"* — HLD §11.1 names the exact shape: *"a 'notes on
    this student' field, or any per-student annotation a later prompt could pick up, would reopen
    the contamination path §7.2 closes"*. It is a reasonable thing for a teacher to ask for, which
    is why the prohibition is a clause rather than a convention.

    Swept over every route, because S13 (`/students/{ref}`) is the obvious home for one and is
    also a legitimate screen — the case has to distinguish a per-student *view* from a per-student
    *writable* field.
    """
    build_console = require(CONSOLE_MODULE, "build_console", issue="#124")

    app = build_console(store=StoreSpy())
    annotation_names = ("note", "notes", "comment", "annotation", "remark", "flag_text")

    offenders: list[str] = []
    routes_rendered = 0
    for screen, route in app.screens().items():
        html = app.render(route).html.lower()
        routes_rendered += 1 if html.strip() else 0
        for name in annotation_names:
            if f'name="{name}' in html or f"name='{name}" in html:
                offenders.append(f"{screen} ({route}) carries a {name!r} field")

    assert routes_rendered >= 5, (
        f"only {routes_rendered} route(s) rendered any markup at all, so this sweep examined "
        f"almost nothing. Every screen in §11.5 is a route, and a sweep over blank pages reports "
        f"no offenders whatever the console does."
    )
    assert not offenders, (
        f"{offenders}. A free-text field attached to a student is the annotation surface §11.1 "
        f"names, and its danger is that nothing about the resulting grades looks wrong."
    )


@pytest.mark.integration
@pytest.mark.writtenahead
def test_tc_console_c04_a_resumed_unit_reads_no_console_written_field():
    """The reachability half, at rung 3 — *"including on resumed or re-run units, which is the
    route that would actually open"*.

    This is the assertion the set operation above cannot make. A console could write only declared
    fields and still open the path, if a **resumed** unit assembled its request from stored state
    that a review action had touched. `FR-ORCH-01` is what makes the property structural — the
    `work_id` hashes the inputs, so a changed input is a different unit — and this case asserts the
    console has not routed around it.

    Asserted against the assembled request rather than against the store, because `CT-JUDGE-01`
    makes `assemble` pure and separable *"precisely so every isolation property is asserted against
    a value in a unit test"*.
    """
    build_console = require(CONSOLE_MODULE, "build_console", issue="#124")

    store = StoreSpy()
    app = build_console(store=store)
    app.perform("review action", submission_ref="sub-0142", new_band="derives_only")

    request = app.assembled_request_for(submission_ref="sub-0142", criterion_id="c4", resumed=True)
    undeclared = _undeclared_paths(request)

    assert not undeclared, (
        f"a resumed unit's request carries {sorted(undeclared)}, which §9.9's whitelist does not "
        f"declare. CT-JUDGE-02: an undeclared field fails validation and is not dispatched — so a "
        f"request that carries one has already routed around the schema."
    )
    assert "derives_only" not in str(request), (
        "the band a teacher selected in the console appears in a resumed unit's scoring request. "
        "That is the UI-into-judgment path CT-CONSOLE-04 exists to close, and R15's point is that "
        "the grades it produces are indistinguishable from correct ones."
    )


#: Every container on the way to a declared field. `criterion.bands.descriptor` contributes
#: `criterion` and `criterion.bands`, both of which a correct request carries and neither of which
#: `SCORING_PROMPT_FIELDS` lists — because §9.9 declares a container by declaring its contents.
_DECLARED_PREFIXES: frozenset[str] = frozenset(
    ".".join(field.split(".")[: depth + 1])
    for field in SCORING_PROMPT_FIELDS
    for depth in range(len(field.split(".")))
)


def _undeclared_paths(payload: object, path: str = "") -> set[str]:
    """Paths in `payload` that §9.9's whitelist does not declare.

    **The walk stops at a declared path.** `SCORING_PROMPT_FIELDS` declares `evidence.spans` and
    `dependency_evidence` as leaves, but §9.9 gives both an internal structure —
    `"spans": [{"start":…, "end":…, "text":…}]`. Recursing past the declared path reports
    `evidence.spans.start` and six of its siblings as undeclared, so a **correct** request produces
    seven violations. Review measured exactly that against §9.9's own example.

    So a declared path terminates the descent: what is below it is that field's declared shape, and
    the question the clause asks is whether a field the schema does not name has appeared.

    The **prefixes** of a declared path are acceptable too, for the same reason from the other end:
    `criterion`, `criterion.bands`, `question` and `evidence` are containers §9.9 declares by
    declaring what is inside them, and reporting them is reporting the schema's own shape.
    """
    if path in SCORING_PROMPT_FIELDS:
        return set()
    if isinstance(payload, dict):
        found: set[str] = set()
        for key, value in payload.items():
            here = f"{path}.{key}" if path else str(key)
            if here in SCORING_PROMPT_FIELDS:
                continue
            if here not in _DECLARED_PREFIXES:
                found.add(here)
                continue
            found |= _undeclared_paths(value, here)
        return found
    if isinstance(payload, (list, tuple)):
        found = set()
        for item in payload:
            found |= _undeclared_paths(item, path)
        return found
    return set()


# --- CT-CONSOLE-05 — loopback, and a refusal that cannot be argued with --------------------------


@pytest.mark.integration
@pytest.mark.writtenahead
def test_tc_console_c05_the_console_binds_loopback_verified_against_the_actual_socket():
    """`CT-CONSOLE-05` / `FR-CONSOLE-05` — asserted on the **bound socket**, not the setting.

    §6.11.19 draws that distinction and it is the whole case. A console configured `127.0.0.1`
    that binds `0.0.0.0` — because a framework default won, or because a container runtime
    rewrote it — reads back as correct from every configuration assertion ever written, and is
    RISK-20 in production: *"an unauthenticated student-record system on a school LAN"*.

    `getsockname()` is the only witness that cannot be faked by the code under test, which is the
    same reason `TC-CONSOLE-C19`'s durations are measured by the test rather than reported by it.
    """
    serve = require(CONSOLE_MODULE, "serve_console", issue="#122")

    server = serve(store=StoreSpy())
    try:
        host, *_ = server.socket.getsockname()
        assert str(host) in LOOPBACK_ADDRESSES, (
            f"the console is actually bound to {host!r}. The configured value says "
            f"{server.bind_address!r}, which is exactly the gap this assertion exists for: a "
            f"console reachable from the LAN has published every student's work with no "
            f"authentication in front of it (RISK-20)."
        )
    finally:
        server.terminate()


@pytest.mark.integration
@pytest.mark.writtenahead
def test_tc_console_c05_every_cloud_hosted_setting_combination_refuses_to_start():
    """The refusal, swept as a **product** — §6.11.19: *"every combination of settings"*.

    A single combination proves the refusal fires once. The failure this sweep is for is a refusal
    keyed on something other than the deployment profile — on the bind address, say, so that
    setting `CONSOLE_BIND` to a routable value under `cloud-hosted` starts a server. That is the
    exact defeat `CT-CONSOLE-20` says must not be possible, and no single combination finds it.

    §3.19 states the boundary being defended: authN/authZ is *"none, deliberately, and the boundary
    that makes that acceptable is FR-CONSOLE-05"*. The refusal is not a deployment preference; it
    is the only thing standing between "no accounts" and "no accounts, on the network".
    """
    serve = require(CONSOLE_MODULE, "serve_console", issue="#122")
    ConsoleBindRefused = require(CONSOLE_MODULE, "ConsoleBindRefused", issue="#122")

    names = list(REFUSAL_SWEEP_SETTINGS)
    started: list[dict[str, object]] = []

    for combination in itertools.product(*(REFUSAL_SWEEP_SETTINGS[name] for name in names)):
        settings = dict(zip(names, combination))
        cfg = hosted_cfg(profile=CLOUD_HOSTED_PROFILE, **settings)
        try:
            server = serve(store=StoreSpy(), cfg=cfg)
        except ConsoleBindRefused:
            continue
        server.terminate()
        started.append(settings)

    assert not started, (
        f"the console started under a cloud-hosted profile for {len(started)} setting "
        f"combination(s), beginning {started[0]}. The refusal keys on the deployment profile "
        f"(CT-CONSOLE-20) or it is not a refusal — it is a default somebody can turn off."
    )


# --- CT-CONSOLE-06 — nothing on the machine, nothing on the network ------------------------------


@pytest.mark.writtenahead
def test_tc_console_c06_no_page_reaches_browser_storage_with_student_text_in_the_data():
    """`CT-CONSOLE-06` / `FR-CONSOLE-17`, asserted from served output with a sentinel in the data.

    §6.11.19 asks for *"a real page load with a sentinel student name present in the data"*. The
    sentinel is the half that transfers: seeding it makes the difference between "no storage call
    is present" and "no storage call **could carry a student**", and the second is what invariant
    12 says. The scan is over the served markup, which is narrower than the plan's browser-level
    instrument — see the module docstring, and the PR.

    §11.7's *"no build step and no client framework"* is what makes this scan meaningful at all: a
    console with a bundler could reach storage from code no scan of the served page would see, and
    with one there is nowhere else for the call to live.
    """
    build_console = require(CONSOLE_MODULE, "build_console", issue="#124")

    app = build_console(store=StoreSpy(), student_name=fixtures.SENTINEL_STUDENT_NAME)
    offenders: list[str] = []
    seen_the_sentinel = False

    for screen, route in app.screens().items():
        html = app.render(route).html
        seen_the_sentinel = seen_the_sentinel or fixtures.SENTINEL_STUDENT_NAME in html
        for api in browser_storage_writes(html):
            offenders.append(f"{screen} ({route}) reaches {api}")

    assert seen_the_sentinel, (
        f"the sentinel student name never appeared on any rendered page, so this sweep ran over a "
        f"console with no student text in it and would pass whatever it did with storage. "
        f"§6.11.19 requires the name to be present in the data."
    )
    assert not offenders, (
        f"{offenders}. Invariant 12 is that no student text is written to browser storage, and the "
        f"plausible violation is a helpful one — the 'remember my place' addition #124's own issue "
        f"names."
    )


@pytest.mark.writtenahead
def test_tc_console_c06_every_page_loads_from_its_own_origin_and_nothing_else(network_guard):
    """`FR-CONSOLE-18` / invariant 13 — zero requests to any origin but its own.

    Two oracles, and they fail differently. The **markup** scan catches a reference that exists,
    whether or not this particular load fetched it — a lazily-loaded font, a `<link>` behind a
    media query. The **socket guard** catches a fetch made at render time from the server side,
    which no markup scan can see. §6.11.19 calls for the network log; the guard is this tier's, and
    `assert_no_network()` is its positive half: it records attempts that were made *and swallowed*,
    so an absence of exceptions is not the same as an absence of traffic.

    HLD §11.7 gives the operational reason rather than the privacy one, and it is the one that
    makes this a `P0`: *"a CDN reference is a console that renders blank at a school with no
    internet — the deployment this system exists for."*
    """
    build_console = require(CONSOLE_MODULE, "build_console", issue="#124")

    app = build_console(store=StoreSpy())
    offenders: list[str] = []
    assets_seen = 0
    for screen, route in app.screens().items():
        html = app.render(route).html
        # The anchor: a page that references **nothing** passes any origin rule ever written, so
        # the sweep has to see real asset references before its silence means anything. HLD §11.7
        # requires one stylesheet, so every page has at least that.
        assets_seen += html.count("<link") + html.count("<script") + html.count("<img")
        for origin in external_origins(html):
            offenders.append(f"{screen} ({route}) references {origin}")

    assert assets_seen, (
        "no route referenced a stylesheet, a script or an image, so this sweep passed over pages "
        "with nothing to load. HLD §11.7 vendors assets locally — it does not omit them."
    )
    assert not offenders, (
        f"{offenders}. Invariant 13 admits no exception — not a font, not a favicon, not an "
        f"analytics pixel. Assets are vendored locally (HLD §11.7)."
    )
    network_guard.assert_no_network()
