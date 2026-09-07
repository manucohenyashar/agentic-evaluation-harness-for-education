"""`TC-PROV-C15` — this module is the sole egress point, static and runtime.

Case: `TC-PROV-C15` (`CT-PROV-15`, **safety property**, P0, rung 0 + rung 4, test plan
§6.11.2 block form). Issue #25 (TS-59).

The clause is a prohibition, so the case's oracle is exact over artifacts: the import graph
(step 1 and step 3) and the recorded connection log (step 2). Any hit fails.

Where each step of the block form lives
---------------------------------------
**Steps 1 and 3, static** run over the walker in `tests/support/import_graph.py`, which
`TC-PROV-05` built (issue #24) and whose tree-level assertions live in
`tests/artifact/test_import_graph.py`. What this file adds is the two things that file
deliberately does not assert:

1. **Cardinality one, not "at most one".** `TC-PROV-05` step 3 asserts *nothing outside
   `M-PROV`*; a tree with no provider module at all would satisfy that vacuously. The clause
   makes a stronger claim on a reviewer's behalf — *"a reviewer may therefore audit egress by
   reading one module"* — and a claim about cardinality one is only kept honest by asserting
   that the one module **exists**.
2. **The adversarial construction.** The block form names it in as many words: *add a
   `requests.get` health check to `M-CONSOLE`'s status screen and a direct SDK import to
   `M-CONFORM` "to compare raw latencies", and assert both turn `TC-PROV-C15` red while every
   `FR-*` case stays green.* A safety-property case without its construction is a title, not
   a test (§6.11). The construction is built here as a synthetic tree holding exactly those
   two modules — `aeh.console` for the status screen, `harness/conform/latency_probe.py` for
   the probe, because `M-CONFORM`'s entry point is a `harness.*` module (§4.7) — plus one
   legitimate neighbour. The case must report exactly the two named modules and nothing else:
   that last part is the *"while every `FR-*` case stays green"* half. A gate that reddens on
   legitimate code gets switched off, and the run then succeeds and looks normal (RISK-32:
   Critical, detectability **No**).

**Step 2, runtime** runs here, in the fast tier, over the journey that exists. The block
form's *full* E2E journey (§6.2) needs `M-ORCH`'s spine, which does not exist yet — so the
journey asserted below is the pipeline surface that does: all three provider
implementations, a recording persisted through `RecordedFixtureProvider`, and the replay of
it from disk by a fresh provider. The assertion is the clause's runtime form, stated
generically so it tightens by itself as the journey grows: **every recorded connection's
stack passes through `M-PROV`**. A health check, a telemetry ping and a font fetch all fail
it — the one below is the health check.

The runtime guard is not the autouse `SocketGuard`. The guard from TS-00 records
`(api, address)`; step 2's oracle is about **the stack that opened the connection**, so this
file carries a guard that attributes every attempt to the `aeh.*` modules on the calling
stack — the same attribution the write audit uses (`tests/support/guards.py`), applied to
egress. Like the autouse guard it *blocks* (the fast tier never touches the wire, loopback
included), and the attribution is read off the record. Two cells prove the attribution
discriminates in both directions:

- a dispatch through `M-PROV`'s own real transport (`_DefaultTransport`, the module's sole
  egress point per `CT-PROV-15`) against a closed loopback port is attributed **to**
  `M-PROV`; and
- the construction's health check — a raw `socket.create_connection`, which is what
  `requests.get` does underneath — is recorded with **no** `M-PROV` frame, which is exactly
  the predicate step 2 asserting failing on. That is the runtime demonstration the block
  form asks the adversarial construction for: the check runs, nothing functional complains,
  and the only thing that sees it is the egress guard.

What is *not* here yet, and where it lands: the §6.2 full journey under this same guard,
when `M-ORCH` closes. The assertion below is already the form that run extends.
"""

from __future__ import annotations

import socket

import pytest

from aeh.prov import PromptPayload, RetryPolicy, _DefaultTransport
from tests.support.guards import NetworkAccessError, _implementation_frames
from tests.support.import_graph import (
    SOURCE_ROOTS,
    egress_capable_modules,
    egress_holders_outside_m_prov,
    scan_tree,
)
from tests.support.prov_contract import (
    IMPL_IDS,
    INJECTED,
    ScriptedTransport,
    flat_ok,
    make_provider,
    model_ref,
    params,
    payload,
    completion,
)

pytestmark = pytest.mark.contract


# --- the runtime egress guard (step 2's instrument) ---------------------------------------------


class EgressAttempt:
    """One connection attempt, with the `aeh.*` modules that were on the stack.

    `labels` is the attribution step 2's predicate reads: *every recorded connection's stack
    passes through `M-PROV`* is `all("M-PROV" in a.labels for a in attempts)`. The labels
    come from the same frame walk the write audit uses, so the two audits attribute the same
    way and a reader only has to learn one convention.
    """

    def __init__(self, api: str, address: object) -> None:
        self.api = api
        self.address = address
        self.labels = tuple(_implementation_frames())

    def __str__(self) -> str:
        via = " -> ".join(self.labels) if self.labels else "(no implementation frame)"
        return f"{self.api}({self.address!r}) via {via}"


class RecordingEgressGuard:
    """Blocks and records outbound connections, attributing each to its stack.

    Step 2's guard, not the autouse one: same APIs patched, same blocking, plus the stack
    attribution the `(api, address)` record cannot carry. Installed over the autouse guard's
    slot (uninstalled first, reinstalled after) so exactly one patch owns each socket API —
    the same composition `TC-PROV-C10` uses when it opens the socket layer on purpose.
    """

    def __init__(self) -> None:
        self.attempts: list[EgressAttempt] = []
        self._originals: dict[str, object] = {}
        self._installed = False

    def install(self) -> None:
        if self._installed:
            return
        self._originals = {
            "connect": socket.socket.connect,
            "connect_ex": socket.socket.connect_ex,
            "create_connection": socket.create_connection,
            "getaddrinfo": socket.getaddrinfo,
            "sendto": socket.socket.sendto,
        }
        guard = self

        def _record(api: str, address: object) -> None:
            guard.attempts.append(EgressAttempt(api, address))
            raise NetworkAccessError(
                f"blocked {api}({address!r}) at {guard.attempts[-1]}. TC-PROV-C15 step 2: "
                "every outbound connection's stack must pass through M-PROV. In the fast "
                "tier nothing connects at all — recorded and stopped before any packet."
            )

        def _connect_guard(sock: socket.socket, address: object, *args: object, **kwargs: object):
            _record("socket.connect", address)

        def _connect_ex_guard(sock: socket.socket, address: object, *args: object, **kwargs: object):
            _record("socket.connect_ex", address)

        def _create_connection_guard(address: object, *args: object, **kwargs: object):
            _record("socket.create_connection", address)

        def _sendto_guard(sock: socket.socket, data: object, *args: object, **kwargs: object):
            # UDP needs no connect(); the address is the last positional or the keyword.
            address = args[-1] if args else kwargs.get("address")
            _record("socket.sendto", address)

        def _getaddrinfo_guard(host: object, port: object, *args: object, **kwargs: object):
            _record("socket.getaddrinfo", (host, port))

        socket.socket.connect = _connect_guard          # type: ignore[method-assign]
        socket.socket.connect_ex = _connect_ex_guard    # type: ignore[method-assign]
        socket.socket.sendto = _sendto_guard            # type: ignore[method-assign]
        socket.create_connection = _create_connection_guard  # type: ignore[assignment]
        socket.getaddrinfo = _getaddrinfo_guard         # type: ignore[assignment]
        self._installed = True

    def uninstall(self) -> None:
        if not self._installed:
            return
        socket.socket.connect = self._originals["connect"]              # type: ignore[method-assign]
        socket.socket.connect_ex = self._originals["connect_ex"]        # type: ignore[method-assign]
        socket.socket.sendto = self._originals["sendto"]                # type: ignore[method-assign]
        socket.create_connection = self._originals["create_connection"]  # type: ignore[assignment]
        socket.getaddrinfo = self._originals["getaddrinfo"]             # type: ignore[assignment]
        self._originals.clear()
        self._installed = False

    def every_stack_passes_through_m_prov(self) -> bool:
        """Step 2's predicate, under the oracle the block form states verbatim."""
        return all("M-PROV" in attempt.labels for attempt in self.attempts)


# --- the case ------------------------------------------------------------------------------------


def test_tc_prov_c15_the_set_of_modules_with_egress_has_cardinality_one(repo_root):
    """`TC-PROV-C15` steps 1+3, stated as the clause states them: the set of modules
    containing an egress-capable import has **cardinality one**, and the one is `M-PROV`.

    `TC-PROV-05`'s tree assertion (issue #24) asserts the complement — nothing outside
    `M-PROV`. This is the half that claim cannot express: a refactor that *deleted* the
    provider module would leave `TC-PROV-05` green over a tree where the clause's audit
    promise ("read one module") points at nothing. The seam must exist, and be exactly one.
    """
    holders = egress_capable_modules(repo_root)

    assert holders == {"aeh.prov"}, (
        "CT-PROV-15: the set of modules holding an egress-capable import must be exactly "
        f"{ {'aeh.prov'} } — the sole seam a reviewer audits egress through. Found: "
        f"{sorted(holders)}. An empty set means the seam itself is gone; anything beyond one "
        "means a second egress point has appeared (RISK-32: Critical, detectability No)."
    )


def test_tc_prov_c15_the_adversarial_construction_turns_the_case_red(tmp_path):
    """`TC-PROV-C15`'s named adversarial construction, built and asserted red.

    The block form: *add a `requests.get` health check to `M-CONSOLE`'s status screen and a
    direct SDK import to `M-CONFORM` "to compare raw latencies". Assert both turn
    `TC-PROV-C15` red while every `FR-*` case stays green.* Both modules are written into a
    synthetic tree at their real shapes — `aeh.console` for the status screen,
    `harness/conform/latency_probe.py` because `M-CONFORM`'s entry point is a `harness.*`
    module (§4.7) — and a legitimate neighbour sits beside them.

    The case is red when **both** are reported, by module and by symbol, and green nowhere
    else: the neighbour must stay clean, because the *"FR cases stay green"* half is this
    gate's precision. A gate that also reddens `aeh.report`'s loopback HTTP server and
    `urllib.parse` gets exempted module by module until it means nothing — and then the next
    health check ships green, which is RISK-32's outcome.
    """
    src = tmp_path / "src" / "aeh"
    src.mkdir(parents=True)
    (src / "__init__.py").write_text("", encoding="utf-8")

    # M-CONSOLE's status screen, with the health check the construction adds.
    (src / "console.py").write_text(
        '"""The console status screen."""\n'
        "\n"
        "\n"
        "def health_check(base_url: str) -> int:\n"
        '    """A quick liveness probe of the configured endpoint."""\n'
        "    import requests\n"
        "\n"
        "    return requests.get(f'{base_url}/health', timeout=2).status_code\n",
        encoding="utf-8",
    )

    # M-CONFORM's latency probe, by direct SDK — "to compare raw latencies".
    harness = tmp_path / "harness" / "conform"
    harness.mkdir(parents=True)
    (tmp_path / "harness" / "__init__.py").write_text("", encoding="utf-8")
    (harness / "__init__.py").write_text("", encoding="utf-8")
    (harness / "latency_probe.py").write_text(
        '"""Compare raw latencies against the SDK directly."""\n'
        "from openai import OpenAI\n",
        encoding="utf-8",
    )

    # The legitimate neighbour: loopback serving and URL parsing are not egress, and the
    # walker must agree — this is the half that keeps the gate a gate.
    (src / "report.py").write_text(
        "import json\n"
        "import urllib.parse\n"
        "from http.server import HTTPServer\n",
        encoding="utf-8",
    )

    violations = scan_tree(tmp_path, roots=SOURCE_ROOTS)
    by_module = {v.module: v.symbol for v in violations if v.kind in ("import", "dynamic-import")}

    assert by_module == {
        "aeh.console": "requests",
        "harness.conform.latency_probe": "openai",
    }, (
        "TC-PROV-C15: the adversarial construction must turn the case red on exactly the two "
        f"named modules. Got: {by_module}. A missed module is a second egress point the gate "
        "blessed; an extra one is a false positive that will get the gate switched off."
    )

    holders = egress_holders_outside_m_prov(tmp_path)
    assert holders == {"aeh.console", "harness.conform.latency_probe"}, (
        "TC-PROV-C15: the adversarial construction must break the cardinality-one audit "
        f"claim. Holders outside M-PROV: {sorted(holders)}."
    )


def test_tc_prov_c15_the_runtime_journey_opens_no_socket_outside_m_prov(
    network_guard, tmp_path
):
    """`TC-PROV-C15` step 2, runtime, over the journey that exists: all three
    implementations dispatch, a recording is persisted through `RecordedFixtureProvider`,
    and a fresh provider replays it from disk — every connection the journey opens (there
    must be none) attributed to `M-PROV`.

    The §6.2 full journey needs `M-ORCH`'s spine and lands with it; this is the clause's
    runtime form, stated as the predicate the run extends — `every_stack_passes_through_m_prov`
    over the guard's whole log — so the assertion tightens by itself as the journey grows.
    The autouse guard is stood down for the call and reinstalled after, the same composition
    `TC-PROV-C10` uses: exactly one instrument owns the socket layer while it runs.
    """
    from aeh.prov import RecordedFixtureProvider

    network_guard.uninstall()
    guard = RecordingEgressGuard()
    guard.install()
    try:
        fixtures_dir = tmp_path / "fixtures"
        ref = model_ref()
        for impl in IMPL_IDS:
            transport = ScriptedTransport(script=[[flat_ok()]], default=flat_ok())
            provider = make_provider(impl, INJECTED, transport, fixture_dir=fixtures_dir)
            if impl == "fixture":
                provider.record(
                    payload(PromptPayload), ref, params(), completion()
                )
            got = provider.complete(payload(PromptPayload), ref, params())
            assert got.text == '{"band": "met"}'

        # The recording survives its provider: a fresh replay over the same fixture dir.
        reloaded = RecordedFixtureProvider(fixture_dir=fixtures_dir)
        again = reloaded.complete(payload(PromptPayload), ref, params())
        assert again.text == '{"band": "met"}'
    finally:
        guard.uninstall()
        network_guard.install()

    assert guard.every_stack_passes_through_m_prov(), (
        "TC-PROV-C15 step 2: a connection was opened outside M-PROV on a journey that must "
        "be hermetic: " + "; ".join(str(a) for a in guard.attempts)
    )


def test_tc_prov_c15_an_m_prov_dispatch_is_attributed_to_m_prov(network_guard):
    """The attribution discriminator's positive cell: egress **by** `M-PROV` is attributed
    to `M-PROV`.

    The provider is the real `LocalServerProvider` over the module's own real transport
    (`_DefaultTransport`, the sole egress point — `CT-PROV-15`) aimed at a closed loopback
    port. The guard stops the connection before any packet — the fast tier never touches the
    wire, and a closed port answers nothing anyway — so the surfaced error is the guard's,
    not the transport's taxonomy. What the cell asserts is the record: the attempt's stack
    carries `M-PROV`, which is what makes step 2's predicate a discriminator rather than a
    flag-everything tripwire. A guard that attributed every attempt to nobody would pass the
    rogue cell by asserting nothing.
    """
    from aeh.prov import LocalServerProvider

    provider = LocalServerProvider(
        base_url="http://127.0.0.1:1/v1",
        transport=_DefaultTransport(),
        policy=RetryPolicy(max_attempts=1, backoff_base_ms=0),
    )

    network_guard.uninstall()
    guard = RecordingEgressGuard()
    guard.install()
    try:
        with pytest.raises(NetworkAccessError):
            provider.complete(payload(PromptPayload), model_ref(), params())
    finally:
        guard.uninstall()
        network_guard.install()

    assert len(guard.attempts) == 1, (
        f"TC-PROV-C15: expected the one egress attempt, got {guard.attempts!r}."
    )
    assert "M-PROV" in guard.attempts[0].labels, (
        "TC-PROV-C15 step 2: an egress made by M-PROV's own transport was not attributed "
        f"to M-PROV (stack labels: {guard.attempts[0].labels}). The predicate "
        "'every stack passes through M-PROV' must be able to answer yes, or it can never "
        "meaningfully answer no."
    )


def _m_console_health_check() -> None:
    """The construction's runtime form: M-CONSOLE's status-screen health check.

    A `requests.get` resolves to exactly this at the socket layer; the raw call is used
    because the construction's point is the *layer* the guard sees, not the client wrapper
    on top of it. Nothing listens on the port: in an unguarded tree this is the health check
    failing to connect — a functional nuisance at worst, which is RISK-32's whole point (the
    run succeeds and looks normal). Under the guard it is the record that convicts.
    """
    with socket.create_connection(("127.0.0.1", 8699), timeout=2):
        pass  # pragma: no cover - the guard blocks before anything connects


def test_tc_prov_c15_a_health_check_outside_m_prov_fails_the_step_2_predicate(
    network_guard,
):
    """The construction's runtime half: the health check's connection is recorded with no
    `M-PROV` frame — step 2's predicate fails on it, which is the case going red.

    Nothing functional fails first: the function is called, it runs, and the only thing that
    sees the attempt is the egress guard's log. That is the gap between this case and the
    functional ones the plan points at — *"including `SEC-03` if that case were scoped only
    to the scoring path"* — and it is why the runtime half exists at all: a static walker
    cannot see a dynamic import resolved at runtime, but the stack that opens the socket
    names whoever opened it.
    """
    network_guard.uninstall()
    guard = RecordingEgressGuard()
    guard.install()
    try:
        with pytest.raises(NetworkAccessError):
            _m_console_health_check()
    finally:
        guard.uninstall()
        network_guard.install()

    assert len(guard.attempts) == 1, (
        f"TC-PROV-C15: expected the health check's one attempt, got {guard.attempts!r}."
    )
    assert not guard.every_stack_passes_through_m_prov() and (
        "M-PROV" not in guard.attempts[0].labels
    ), (
        "TC-PROV-C15 step 2: the health check's connection was attributed to M-PROV "
        f"({guard.attempts[0].labels}). The predicate must fail on exactly the construction "
        "the plan names — an attribution that absolves the rogue makes the runtime half "
        "decorative."
    )
