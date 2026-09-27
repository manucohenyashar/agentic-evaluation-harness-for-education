"""TS-125 (#501): the TypeSafe SDK stays inside `aeh.prov`, ships only as an extra, and logs no
student text (design 1.8, §3.12). Jev test plan §5.8, §6.5 and §6.11.6. Written ahead of #498,
except the arms that hold today and must keep holding (marked below as green pins).

| Case | Asserted |
|---|---|
| TC-PROV-52 | Static: no `aeh` module but `prov` imports the SDK, and `prov` only inside a function. Subprocess: importing the harness and building every non-cloud provider loads none of `typesafe_sdk`, `httpx2`, `pydantic`, `tenacity`; building `JevOpenRouterProvider` loads the SDK; every value reachable from a returned `Decision` is a harness type |
| TC-PROV-53 | `pyproject.toml` has no core dependency and the exact-pinned `jev-cloud` extra; `requirements-dev.txt` pins it; with the SDK unimportable, building the cloud decision provider refuses naming `jev-cloud`, while the non-cloud providers and the harness modules still load |
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


def _run_python(code: str, *, block_sdk: bool = False) -> subprocess.CompletedProcess:
    prelude = f"import sys; sys.path[:0] = [{str(ROOT / 'src')!r}, {str(ROOT)!r}]\n"
    if block_sdk:
        prelude += "for _m in ('typesafe_sdk',): sys.modules[_m] = None\n"
    return subprocess.run([sys.executable, "-c", prelude + code], capture_output=True, text=True, cwd=ROOT,
                          timeout=120)


# --- TC-PROV-52 ----------------------------------------------------------------------------------

def _sdk_imports() -> dict[str, list[tuple[int, bool]]]:
    """`{module file: [(line, at_module_level), ...]}` for every import of an SDK module in
    `src/aeh`. An import inside a function or method body is not at module level."""
    found: dict[str, list[tuple[int, bool]]] = {}
    for path in sorted((ROOT / "src" / "aeh").glob("*.py")):
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
        assert type(value).__module__ in allowed, f"{type(value).__module__}.{type(value).__name__} leaked"
        if hasattr(value, "__dataclass_fields__"):
            pending.extend(getattr(value, name) for name in value.__dataclass_fields__)
        elif isinstance(value, dict) or type(value).__name__ == "mappingproxy":
            pending.extend(value.keys())
            pending.extend(value.values())
        elif isinstance(value, (list, tuple)):
            pending.extend(value)


# --- TC-PROV-53 ----------------------------------------------------------------------------------

def test_tc_prov_53_the_core_install_stays_dependency_free_and_dev_pins_the_sdk() -> None:
    """Green pin: ADR-11's empty core, and the exact dev-tier pin (NFR-PROV-10)."""
    project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]
    assert project.get("dependencies") == []
    dev = (ROOT / "requirements-dev.txt").read_text(encoding="utf-8")
    assert re.search(r"^typesafe-sdk==0\.7\.2\s*$", dev, re.M), "the dev tier pins the SDK exactly"


def test_tc_prov_53_the_sdk_ships_as_the_jev_cloud_extra_and_its_absence_is_refused_by_name(tmp_path) -> None:
    """FR-PROV-42: the extra `jev-cloud` exact-pins the SDK. With the SDK unimportable, building
    the cloud decision provider (what run start does, FR-PIPE-11) raises `ConfigurationError`
    naming the extra, while the harness and the non-cloud providers still load and build."""
    project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]
    assert project.get("optional-dependencies", {}).get("jev-cloud") == ["typesafe-sdk==0.7.2"]
    blocked = _run_python(
        "from aeh.conf import ConfigurationError, ModelRef\n"
        "from aeh.prov import decision_provider_for\n"
        "ref = ModelRef(role='decision', provider='openrouter-jev', build_id='openrouter/typesafe/jev-1.13@2026-09-01', quantization=None)\n"
        "try:\n"
        "    decision_provider_for(ref, api_key='k')\n"
        "    print('BUILT')\n"
        "except ConfigurationError as e:\n"
        "    print('REFUSED', e)\n", block_sdk=True)
    assert blocked.returncode == 0, blocked.stderr
    assert blocked.stdout.startswith("REFUSED") and "jev-cloud" in blocked.stdout, blocked.stdout
    others = _run_python(
        "import aeh.judge, aeh.pipeline, aeh.conform\n"
        "from aeh.prov import OpenJevLocalProvider, RecordedFixtureProvider\n"
        f"OpenJevLocalProvider(); RecordedFixtureProvider(fixture_dir={str(tmp_path)!r}); print('OK')\n", block_sdk=True)
    assert others.returncode == 0 and others.stdout.strip() == "OK", others.stderr


@pytest.mark.integration
def test_tc_prov_53_a_cloud_run_without_the_sdk_refuses_at_start_before_any_lease(tmp_path, monkeypatch) -> None:
    """The plan's run-level arm: with the SDK unimportable, `run_to_completion` for a
    `cloud-hosted` run whose decision provider is `openrouter-jev` (the composer builds it, FR-PIPE-11)
    raises `ConfigurationError` naming `jev-cloud`, with no unit leased and no model call made."""
    from aeh.conf import CohortRef, ConfigurationError, resolve_run_config
    from aeh.pipeline import run_to_completion
    from tests.support import pipe_world
    from tests.support.conf_builders import hosted_cfg

    monkeypatch.setitem(sys.modules, "typesafe_sdk", None)
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-TEST")
    world = pipe_world.replay_world(tmp_path / "d")
    try:
        world.build_run()
        world.start_run()
        leased_before = world.handle.query("SELECT count(*) n FROM work_unit WHERE status != 'pending'")[0]["n"]
        replays_before = world.provider.replayed_calls
        cloud = resolve_run_config(hosted_cfg("cloud-hosted", HARNESS_DECISION_ENGINE="jev",
                                              HARNESS_JEV_BUILD="openrouter/typesafe/jev-1.13@2026-09-17"),
                                   CohortRef(cohort_id=world.cohort_id, consent_class="synthetic"))
        with pytest.raises(ConfigurationError) as caught:
            run_to_completion(world.store, world.run_id, provider=world.provider, run_config=cloud,
                              **pipe_world.corpus_refs())
        assert "jev-cloud" in str(caught.value)
        leased_after = world.handle.query("SELECT count(*) n FROM work_unit WHERE status != 'pending'")[0]["n"]
        assert leased_after == leased_before and world.provider.replayed_calls == replays_before
    finally:
        world.store.close()


@pytest.mark.integration
def test_tc_prov_53_an_engine_off_run_completes_with_the_sdk_unimportable(tmp_path, monkeypatch) -> None:
    """Green pin: an engine-off run never touches the SDK, so blocking its import (even after
    another test loaded it) changes nothing. A path that builds a cloud provider at run time,
    for its capabilities say, turns this red."""
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
        assert type(caught.value).__module__ == "aeh.prov", type(caught.value)
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
