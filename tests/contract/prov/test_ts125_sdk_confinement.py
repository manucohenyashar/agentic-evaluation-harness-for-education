"""TS-125 (#501): the TypeSafe SDK stays inside `aeh.prov`, ships as a standard dependency (ADR-36;
it was the `jev-cloud` extra until the operator-requirements delta, whose TC-PROV-53 flip #613
wrote), and logs no student text (design 1.8, §3.12). Jev test plan §5.8, §6.5 and §6.11.6.
Written ahead of #498, except the arms that hold today and must keep holding (marked below as
green pins).

| Case | Asserted |
|---|---|
| TC-PROV-52 | Static: no `aeh` module but `prov` imports the SDK, and `prov` only inside a function. Subprocess: importing the harness and building every non-cloud provider loads none of `typesafe_sdk`, `httpx2`, `pydantic`, `tenacity`; building `JevOpenRouterProvider` loads the SDK; every value reachable from a returned `Decision` is a harness type |
| TC-PROV-53 | Flipped (#613, FR-PROV-42 amended): `typesafe-sdk==0.7.2` is a `[project].dependencies` string with no extra; no `src/aeh` module names a retired extra (the packaging refusal is deleted); `decision_provider_for` builds `JevOpenRouterProvider` under the default resolution; engine-off and edge-local (engine on) runs complete with the SDK unimportable |
| SEC-23 | With the `typesafe_sdk` logger at DEBUG, no captured record from any logger carries the state sentinel (exception text included), no SDK record below WARNING is emitted, and the SDK's forward-compatibility WARNING still is |
| TC-PROV-C29 | CT-PROV-29, safety-shaped: TC-PROV-52's scan and walk, SEC-23's capture, and no SDK exception type escaping `decide` |
| TC-PROV-C30 | CT-PROV-30, safety-shaped: every request of a `decide` passes the programmed `Transport`, stamped by the SDK, with no SDK retry, under a socket guard that sees no connect |
"""

from __future__ import annotations

import ast
import json
import logging
import re
import subprocess
import sys
import tomllib
from pathlib import Path

import pytest

from aeh.conf import ModelRef
from aeh.prov import DecisionRequest, HttpResponse, JevOpenRouterProvider, NoulQuestion, ScoreQuestion
from tests.support.clock import FrozenClock
from tests.support.guards import SocketGuard
from tests.support.source_tree import aeh_module_paths, defined_in

pytestmark = pytest.mark.contract
ROOT = Path(__file__).resolve().parents[3]
SDK_MODULES = ("typesafe_sdk", "httpx2", "pydantic", "tenacity")
JEV_REF = ModelRef(role="decision", provider="openrouter-jev",
                   build_id="openrouter/typesafe/jev-1.13@2026-09-01", quantization=None)
SENTINEL = "ZQXJ-8-STUDENT-TEXT"


class _Transport:
    def __init__(self, *responses) -> None:
        self.responses = list(responses)
        self.requests = []

    def send(self, request):  # noqa: ANN001
        self.requests.append(request)
        return self.responses[min(len(self.requests) - 1, len(self.responses) - 1)]


def _ok(body: dict) -> HttpResponse:
    return HttpResponse(200, {}, json.dumps(body).encode("utf-8"))


def _headers(request) -> dict[str, str]:  # noqa: ANN001
    return {str(k).lower(): str(v) for k, v in dict(request.headers).items()}


def _noul_request(state: str = "s") -> DecisionRequest:
    return DecisionRequest(state=state, questions=(NoulQuestion("ok", "x"),))


def _noul_body(**extra_answers) -> dict:
    return {"model": "typesafe/jev-1.13", "usage": {"input_tokens": 1, "output_tokens": 0},
            "answers": {"ok": {"type": "noul", "noul": 0.9}, **extra_answers}}


def _run_python(code: str) -> subprocess.CompletedProcess:
    prelude = f"import sys; sys.path[:0] = [{str(ROOT / 'src')!r}, {str(ROOT)!r}]\n"
    return subprocess.run([sys.executable, "-c", prelude + code], capture_output=True, text=True, cwd=ROOT,
                          timeout=120)


# --- TC-PROV-52 ----------------------------------------------------------------------------------

def _sdk_imports() -> dict[str, list[tuple[int, bool]]]:
    """`{module file: [(line, at_module_level), ...]}` for every import of an SDK module in
    `src/aeh`. An import inside a function or method body is not at module level."""
    found: dict[str, list[tuple[int, bool]]] = {}
    for path in aeh_module_paths(ROOT / "src" / "aeh"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        functions = [n for n in ast.walk(tree) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]
        inside = {id(child) for f in functions for child in ast.walk(f)}
        for node in ast.walk(tree):
            names = ([a.name for a in node.names] if isinstance(node, ast.Import)
                     else [node.module or ""] if isinstance(node, ast.ImportFrom) else [])
            if any(n.split(".")[0] in SDK_MODULES for n in names):
                found.setdefault(path.name, []).append((node.lineno, id(node) not in inside))
    return found


def test_tc_prov_52_no_module_but_prov_imports_the_sdk_and_never_at_top_level() -> None:
    """Green pin: holds before #498 (nothing imports the SDK) and must hold after it."""
    found = _sdk_imports()
    assert set(found) <= {"prov.py"}, f"the SDK is imported outside aeh.prov: {found}"
    assert not [line for line, top in found.get("prov.py", []) if top], (
        "aeh.prov imports the SDK at module level, so `import aeh.prov` would load it")


def _loaded_after(steps: str) -> set[str]:
    code = steps + f"\nprint(json.dumps([m for m in {SDK_MODULES!r} if m in sys.modules]))"
    out = _run_python("import json\n" + code)
    assert out.returncode == 0, out.stderr
    return set(json.loads(out.stdout.strip().splitlines()[-1]))


def test_tc_prov_52_the_harness_and_non_cloud_providers_load_no_sdk_module(tmp_path) -> None:
    """Green pin: importing the harness and building every non-cloud provider loads none of the
    SDK or its dependencies (RISK-90)."""
    loaded = _loaded_after(
        "import aeh, aeh.prov, aeh.judge, aeh.conform, aeh.pipeline\n"
        "from aeh.prov import OpenJevLocalProvider, OpenJevSmallLocalProvider, RecordedFixtureProvider\n"
        f"OpenJevLocalProvider(); OpenJevSmallLocalProvider(); RecordedFixtureProvider(fixture_dir={str(tmp_path)!r})")
    assert loaded == set(), f"loaded without a cloud provider: {sorted(loaded)}"


def test_tc_prov_52_building_the_cloud_provider_loads_the_sdk_and_decisions_stay_harness_typed() -> None:
    loaded = _loaded_after("from aeh.prov import JevOpenRouterProvider\nJevOpenRouterProvider(api_key='k')")
    assert "typesafe_sdk" in loaded, "JevOpenRouterProvider is built on the TypeSafe SDK (FR-PROV-38)"
    transport = _Transport(_ok(_noul_body()))
    decision = JevOpenRouterProvider(api_key="k", transport=transport, clock=FrozenClock()).decide(
        _noul_request(), JEV_REF)
    assert _headers(transport.requests[0]).get("x-typesafe-sdk", "").startswith("typesafe-sdk/")
    _assert_harness_typed(decision)


def _assert_harness_typed(decision) -> None:  # noqa: ANN001
    """Every value reachable from `decision` is a harness or standard-library type (CT-PROV-29)."""
    allowed = {"builtins", "decimal", "types", "aeh.prov"}
    pending, seen = [decision], set()
    while pending:
        value = pending.pop()
        if id(value) in seen:
            continue
        seen.add(id(value))
        assert type(value).__module__ in allowed or defined_in(type(value), "aeh.prov"), f"{type(value).__module__}.{type(value).__name__} leaked"
        if hasattr(value, "__dataclass_fields__"):
            pending.extend(getattr(value, name) for name in value.__dataclass_fields__)
        elif isinstance(value, dict) or type(value).__name__ == "mappingproxy":
            pending.extend(value.keys())
            pending.extend(value.values())
        elif isinstance(value, (list, tuple)):
            pending.extend(value)


# --- TC-PROV-53 ----------------------------------------------------------------------------------
#
# Flipped by #613 (operator-requirements test plan §5.0, FR-PROV-42 amended, ADR-36). The SDK is a
# standard dependency now, so the `sys.modules["typesafe_sdk"] = None` refusal arm and the
# cloud-run refusal arm are DELETED: there is no install without the SDK left to refuse. What
# survives is CT-PROV-29's import-discipline half — an engine-off run and an edge-local run still
# complete without importing the SDK — and construction under the default resolution. The pin and
# the no-packaging-check arms are red until #614 lands (`writtenahead`, keyed there).

#: FR-STORE-20 / NFR-PROV-10, transcribed: the exact pin, as a declared string.
SDK_PIN = "typesafe-sdk==0.7.2"

#: The retired extras' names. After ADR-36 no shipped module may mention either: a message naming
#: `jev-cloud` is the deleted packaging check, or an install instruction for an extra that no
#: longer exists.
RETIRED_EXTRAS = ("jev-cloud", "live-ingest")


@pytest.mark.writtenahead
def test_tc_prov_53_the_sdk_is_exact_pinned_in_the_core_dependencies() -> None:
    """The pin arm (flipped): `typesafe-sdk==0.7.2` is a `[project].dependencies` string, and no
    extra carries it — the SDK installs with `pip install .` or not at all."""
    project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]
    dependencies = project.get("dependencies") or []
    assert SDK_PIN in dependencies, (
        f"[project].dependencies is {dependencies}; FR-PROV-42 (amended) pins {SDK_PIN!r} there")
    sdk_entries = [d for d in dependencies if re.match(r"typesafe[-_]sdk\b", d, re.I)]
    assert sdk_entries == [SDK_PIN], f"the SDK is declared more than once or loosely: {sdk_entries}"
    assert "optional-dependencies" not in project, project.get("optional-dependencies")


@pytest.mark.writtenahead
def test_tc_prov_53_no_shipped_module_keeps_a_packaging_check_naming_an_extra() -> None:
    """The deleted refusal (negative): no module under `src/aeh` names a retired extra. Today
    `aeh.prov.jev_openrouter` raises `ConfigurationError` naming `jev-cloud` when the SDK is
    absent; FR-PROV-42 (amended) deletes that check, and with it the only reason to name the extra."""
    hits = [f"{path.relative_to(ROOT).as_posix()}:{n}"
            for path in sorted((ROOT / "src" / "aeh").rglob("*.py"))
            for n, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1)
            if any(extra in line for extra in RETIRED_EXTRAS)]
    assert hits == [], f"shipped code still names a retired extra (ADR-36): {hits}"


def test_tc_prov_53_the_cloud_provider_constructs_under_the_default_resolution(monkeypatch) -> None:
    """Construction arm (green, and must stay green): the factory builds `JevOpenRouterProvider`
    for an `openrouter-jev` ref with no seam injected — only the API key from the environment, as
    a run start resolves it (FR-PIPE-11). No packaging check stands in the way."""
    from aeh.prov import decision_provider_for

    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-TEST")
    provider = decision_provider_for(JEV_REF)
    assert type(provider) is JevOpenRouterProvider, type(provider)


@pytest.mark.integration
def test_tc_prov_53_an_engine_off_run_completes_with_the_sdk_unimportable(tmp_path, monkeypatch) -> None:
    """Surviving arm (green pin): an engine-off run never touches the SDK, so blocking its import
    (even after another test loaded it) changes nothing. A path that builds a cloud provider at
    run time, for its capabilities say, turns this red."""
    from tests.support import pipe_world

    monkeypatch.setitem(sys.modules, "typesafe_sdk", None)
    world = pipe_world.replay_world(tmp_path / "d")
    try:
        world.build_run()
        world.start_run()
        outcome = pipe_world.drive_composed(world)
        assert outcome.status == "complete"
    finally:
        world.store.close()


@pytest.mark.integration
def test_tc_prov_53_an_edge_local_run_with_the_engine_on_completes_with_the_sdk_unimportable(
        tmp_path, monkeypatch) -> None:
    """Surviving arm (green pin): an `edge-local` run whose decision engine is ON — F-JEV-DECISIONS'
    fixture engine pre-screening seat 0 — also completes with the SDK blocked. The engine being on
    is the point: an engine-off run proves nothing about the decision leg, and a decision leg
    that reached for the SDK whatever the provider would pass the engine-off arm and fail here."""
    from tests.support import pipe_world

    monkeypatch.setitem(sys.modules, "typesafe_sdk", None)
    world = pipe_world.jev_replay_world(tmp_path / "d")
    try:
        world.build_run()
        assert world.resolved.backend_profile == "edge-local", world.resolved.backend_profile
        world.start_run()
        outcome = pipe_world.drive_composed(world)
        assert outcome.status == "complete", outcome
        prescreens = world.handle.query("SELECT count(*) n FROM decision_prescreen")[0]["n"]
        assert prescreens > 0, "precondition: the decision leg ran (the engine is on)"
    finally:
        world.store.close()


# --- SEC-23 --------------------------------------------------------------------------------------

def _sdk_calls_under_capture(caplog, monkeypatch) -> tuple[list[logging.LogRecord], list[BaseException]]:
    """Three `decide` calls whose state holds the sentinel: OK, a 422 echoing it, and a body with
    an answer type the SDK does not model (it warns). The SDK logger is set to DEBUG, as an
    operator would to diagnose a slow run."""
    monkeypatch.setenv("TYPESAFE_LOG_LEVEL", "debug")
    monkeypatch.setenv("HARNESS_RETRY_MAX", "1")
    caplog.set_level(logging.DEBUG)
    state = f"### submission\n{SENTINEL}"
    echo = HttpResponse(422, {}, json.dumps({"error": {"code": 422, "message": f"invalid: {SENTINEL}"}}).encode())
    errors: list[BaseException] = []
    for response in (_ok(_noul_body()), echo, _ok(_noul_body(extra={"type": "hologram", "value": 1}))):
        provider = JevOpenRouterProvider(api_key="k", transport=_Transport(response), clock=FrozenClock())
        # Raised to DEBUG *after* construction, as an operator's later logging reconfiguration
        # would: only a filter attached to the logger (NFR-PROV-11) survives it, whereas a
        # constructor that merely lowers the level would be overridden here. caplog restores
        # the level at teardown, so nothing leaks into other tests.
        caplog.set_level(logging.DEBUG, logger="typesafe_sdk")
        try:
            provider.decide(_noul_request(state), JEV_REF)
        except Exception as error:  # noqa: BLE001 - the 422 and the unmodelled answer both raise
            errors.append(error)
    return list(caplog.records), errors


def _chain(error: BaseException) -> list[BaseException]:
    """Every exception reachable from `error` through `__cause__` AND `__context__`. Deliberately
    strict: CT-PROV-29 allows no SDK object (and so none of the up-to-200 body bytes an SDK error
    carries) to be reachable from a raised exception. A `raise ... from None` inside the handler
    still leaves the SDK error in `__context__`; clear it, as the SDK's own transport does, rather
    than loosening this walk."""
    seen: list[BaseException] = []
    pending = [error]
    while pending:
        link = pending.pop()
        if link is None or any(link is s for s in seen):
            continue
        seen.append(link)
        pending.extend((link.__cause__, link.__context__))
    return seen


def test_sec_23_no_log_record_carries_student_text(caplog, monkeypatch) -> None:
    records, errors = _sdk_calls_under_capture(caplog, monkeypatch)
    formatter = logging.Formatter()
    for record in records:
        text = record.getMessage() + (formatter.formatException(record.exc_info) if record.exc_info else "")
        assert SENTINEL not in text, f"{record.name}:{record.levelname} carries student text"
    sdk = [r for r in records if r.name.startswith("typesafe_sdk")]
    assert not [r for r in sdk if r.levelno < logging.WARNING], "the SDK's DEBUG/INFO body logging is filtered"
    assert any(r.levelno >= logging.WARNING and "hologram" in r.getMessage() for r in sdk), (
        "the SDK's forward-compatibility WARNING still reaches the log (the filter drops only lower levels)")
    for error in errors:
        for link in _chain(error):
            assert SENTINEL not in repr(link) and SENTINEL not in str(link), type(link).__name__


# --- TC-PROV-C29 ---------------------------------------------------------------------------------

def test_tc_prov_c29_the_sdk_never_crosses_the_module_boundary(caplog, monkeypatch) -> None:
    """Safety-shaped (RISK-88/89/90). Adversarial constructions (plan §6.11.6): (a) `from
    typesafe_sdk import Noul` at the top of `aeh/judge.py` fails the scan; (b) an unmapped SDK
    exception let through fails the raised-type check; (c) a client built without `base_url=`
    fails TC-PROV-48's environment arm (TS-124)."""
    found = _sdk_imports()
    assert set(found) == {"prov.py"} and not [ln for ln, top in found["prov.py"] if top], found
    transport = _Transport(_ok(_noul_body()))
    decision = JevOpenRouterProvider(api_key="k", transport=transport, clock=FrozenClock()).decide(_noul_request(), JEV_REF)
    _assert_harness_typed(decision)
    import typesafe_sdk

    for status in (418, 529):
        failing = _Transport(HttpResponse(status, {}, b'{"error": "x"}'))
        with pytest.raises(Exception) as caught:
            JevOpenRouterProvider(api_key="k", transport=failing, clock=FrozenClock(),
                                  ).decide(_noul_request(), JEV_REF)
        assert defined_in(type(caught.value), "aeh.prov"), type(caught.value)
        assert not isinstance(caught.value, typesafe_sdk.TypeSafeError)
        assert _headers(failing.requests[0]).get("x-typesafe-sdk", "").startswith("typesafe-sdk/")
    records, _ = _sdk_calls_under_capture(caplog, monkeypatch)
    assert not [r for r in records if r.name.startswith("typesafe_sdk") and r.levelno < logging.WARNING]


# --- TC-PROV-C30 ---------------------------------------------------------------------------------

def test_tc_prov_c30_every_byte_passes_the_transport_with_no_sdk_retry(monkeypatch) -> None:
    """Safety-shaped (RISK-85/86/87). Adversarial constructions: (a) the SDK's default retries
    left on put `X-TypeSafe-Retry-Count` on the second send; (b) `http_client=httpx2.Client()`
    instead of the adapter leaves the transport spy at 0 and trips the socket guard; (c) cost
    read from the SDK model is TS-124's TC-PROV-50."""
    monkeypatch.setenv("HARNESS_RETRY_MAX", "3")
    body = {**_noul_body(), "answers": {"band": {"type": "score", "score": 1.0, "confidence": 0.9,
                                                 "probabilities": {"0": 0.05, "1": 0.9, "2": 0.05},
                                                 "legend": {"0": "a", "1": "b", "2": "c"}}}}
    request = DecisionRequest(state="s", questions=(ScoreQuestion("band", "x", ("a", "b", "c")),))
    transport = _Transport(HttpResponse(500, {}, b"{}"), HttpResponse(500, {}, b"{}"), _ok(body))
    guard = SocketGuard()
    guard.install()
    try:
        JevOpenRouterProvider(api_key="k", transport=transport, clock=FrozenClock()).decide(request, JEV_REF)
    finally:
        guard.uninstall()
    assert guard.attempts == [], "a request bypassed the programmed transport"
    assert len(transport.requests) == 3
    for sent in transport.requests:
        headers = _headers(sent)
        assert headers.get("x-typesafe-sdk", "").startswith("typesafe-sdk/0.7.2")
        assert "x-typesafe-retry-count" not in headers
        assert sent.url.endswith("/api/v1/systemone")
        document = json.loads(bytes(sent.body).decode("utf-8"))
        assert document["provider"]["allow_fallbacks"] is False and document["provider"]["zdr"] is True
