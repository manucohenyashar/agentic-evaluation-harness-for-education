"""`TS-166` (issue #699) — `Requires` pairwise integration into **`M-AUTHOR`'s three upstream
dependencies**, checked against the real counterpart at rung 2 (real dependency, recorded
transport). A `Requires` row with no case is an unverified assumption wearing a citation; each
case here proves the assumption was founded — that the consumer's actual usage matches the
clause it cites (test plan §5.4, design delta §3.1 *Requires*).

| Case | Pair | Clause checked here |
|---|---|---|
| TC-REQ-134 | `M-AUTHOR` → `M-CONF` | `panel_for_profile` returns the profile's ordered, resolved judge refs without a cohort; an empty panel raises rather than returning `()` (CT-CONF-23, CT-CONF-03) |
| TC-REQ-135 | `M-AUTHOR` → `M-PROV` | Recorded replay is exact — a changed request misses loudly, never stale-replays; every call rides `InferenceProvider`; retries and retention are the provider's, applied once (CT-PROV-10, CT-PROV-15) |
| TC-REQ-136 | `M-AUTHOR` → `M-PKG` | Every fixture draft either builds after review completion or is refused naming file + field + reason (CT-PKG-23, FR-PKG-28) |

Disclosed shape bets (the landing reconciles them, never silently):

- TC-REQ-134 passes `parse_config_document`'s output — the parsed config *document*, with the
  profile's `[[panel]]` already `ModelRef`s and `[[escalation_judge]]` still raw tables, the
  shape the file-reading door leaves — as `cfg`. If the landed surface wants the selected or
  resolved form instead, the call shape is the reconciliation point.
- TC-REQ-135's scripted replies are deliberately unparseable: every reasoning step exhausts the
  chain and resolves nothing, which is itself deterministic. The transport discipline is the
  oracle here, not the draft's content — that is #690's own suite's job. A `changed request`
  is asserted to miss **loudly** (`FixtureMissingError` out of `draft()`): the recorded tier
  must not silently degrade a drifted recording into placeholders (design delta §5.2: a prompt
  bump "fails loudly instead of replaying stale recordings"). If the landing treats
  `FixtureMissingError` as FR-AUTHOR-05's fallback trigger instead, this assertion is the
  reconciliation point. `AuthoringSettings()` is constructed bare — the knobs carry production
  defaults per seam 3.
- TC-REQ-136 reads two corpus shapes that #686 owns: each fixture's `expected.toml` must
  declare the per-fixture build outcome (read as `[build] outcome = "builds" | "refused"`) and
  the scripted review answers (read as `[review] answers`, item id → value). A fixture whose
  declared shape is missing fails legibly naming the corpus clause — the case must not derive
  the fixture's expected outcome from itself, which would make the dichotomy vacuous in the
  weak direction (an incompletely-completed review silently turning a "builds" fixture into a
  "refused" one).

Markers: `contract` and `integration` (§4.7).
"""

from __future__ import annotations

import ast
import copy
import json
import os
import re
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

import pytest

from aeh.prov import HttpResponse, LocalServerProvider, RecordedFixtureProvider
from aeh.prov.live import _fields_from_wire
from tests.support.impl import AUTHOR_MODULE, CONF_MODULE, require, require_attr, require_path
from tests.support.prov_contract import CountingClock, flat_ok
from tests.support.source_tree import package_source

#: All three cases are red by design (test plan §8.2): each waits on its implementing story —
#: #687 for TC-REQ-134, #690 for TC-REQ-135, #686+#690+#696 for TC-REQ-136 — so the whole
#: module carries `writtenahead` until the last blocker closes.
pytestmark = [pytest.mark.contract, pytest.mark.integration, pytest.mark.writtenahead]

#: The repo root, three levels up from `tests/contract/requires/`.
REPO_ROOT = Path(__file__).resolve().parents[3]


@dataclass
class WireTransport:
    """A transport that answers each POST through `reply(fields)` and keeps every dispatched body.

    `script` holds responses (or exceptions) served first, one per attempt, before `reply` is
    consulted. That is how a retry is programmed."""

    reply: object
    build: str = "served-build-7"
    script: list = field(default_factory=list)
    bodies: list = field(default_factory=list)
    attempts: int = 0

    def send(self, request):
        if request.method != "POST":
            return HttpResponse(200, {}, b"{}")
        self.attempts += 1
        if self.script:
            outcome = self.script.pop(0)
            if isinstance(outcome, Exception):
                raise outcome
            return outcome
        body = json.loads(request.body.decode("utf-8")) if isinstance(request.body, bytes) else request.body
        self.bodies.append(body)
        return flat_ok(text=self.reply([tuple(f) for f in _fields_from_wire(body)]), build=self.build)

    def fields(self):
        return [[tuple(f) for f in _fields_from_wire(body)] for body in self.bodies]


def wire_provider(transport: WireTransport) -> LocalServerProvider:
    return LocalServerProvider(base_url="http://local/v1", transport=transport, clock=CountingClock())


def _provider_spy(monkeypatch) -> list:
    """Count every `complete()` the three provider implementations are asked for (TC-REQ-67's
    sweep). A clause that must precede any provider call proves itself against zero here."""
    import aeh.prov as prov

    calls = []
    for cls in (prov.RecordedFixtureProvider, prov.LocalServerProvider, prov.OpenRouterProvider):
        original = cls.complete
        monkeypatch.setattr(
            cls, "complete",
            lambda self, *a, _o=original, _c=cls, **k: calls.append(_c.__name__) or _o(self, *a, **k))
    return calls


def _tree_snapshot(root: Path) -> list:
    """Every file under `root` as `(relative path, size)`, sorted — the file-state oracle for a
    no-write clause against a fresh data dir, where any row write needs a file first."""
    return sorted(
        (str(p.relative_to(root)), p.stat().st_size)
        for p in root.rglob("*") if p.is_file()
    )


# -- TC-REQ-134 ----------------------------------------------------------------------------------


_DEV_CI_CONFIG = """\
HARNESS_PROFILE = "dev-ci"
prompt_template_v = "judge-prompt/3"

[profiles.dev-ci.transcriber]
role = "transcriber"
provider = "openrouter"
build_id = "openai/whisper-1@2024-11-02"

[[profiles.dev-ci.panel]]
role = "judge"
provider = "openrouter"
build_id = "meta-llama/llama-3.3-70b-instruct@2024-12-06"

[[profiles.dev-ci.panel]]
role = "judge"
provider = "openrouter"
build_id = "qwen/qwen-2.5-72b-instruct@2024-09-19"

[[profiles.dev-ci.panel]]
role = "judge"
provider = "openrouter"
build_id = "mistralai/mistral-large@2024-11-18"

[[profiles.dev-ci.escalation_judge]]
role = "judge"
provider = "openrouter"
build_id = "qwen/qwen-2.5-72b-instruct@2024-09-19"

[[profiles.dev-ci.escalation_judge]]
role = "judge"
provider = "openrouter"
build_id = "qwen/qwen-2.5-72b-instruct@2024-09-19"
quantization = "q4"

[[profiles.dev-ci.escalation_judge]]
role = "judge"
provider = "openrouter"
build_id = "deepseek/deepseek-v3@2024-12-01"
"""

_DEV_CI_EMPTY_PANEL_CONFIG = """\
HARNESS_PROFILE = "dev-ci"

[profiles.dev-ci.transcriber]
role = "transcriber"
provider = "openrouter"
build_id = "openai/whisper-1@2024-11-02"

[[profiles.dev-ci.escalation_judge]]
role = "judge"
provider = "openrouter"
build_id = "deepseek/deepseek-v3@2024-12-01"
"""


def test_tc_req_134_the_authoring_chain_is_panel_for_profile(tmp_data_dir, monkeypatch):
    """`TC-REQ-134` (`M-AUTHOR` → `M-CONF`, FR-CONF-33, CT-CONF-23, CT-CONF-03): the chain
    M-AUTHOR reasons with is `panel_for_profile`'s return, exactly as the profile's own sections
    declare it — the `[[panel]]` refs in declared order, then the `[[escalation_judge]]` refs in
    declared order, de-duplicated by build identity, each resolved per CT-CONF-03 — and nothing
    else: no cohort, no consent gate, no run row, no provider call, no cfg mutation, no
    environment read beyond what `ModelRef` resolution already does. A profile whose section
    carries escalation judges but no `[[panel]]` raises `ConfigurationError` — it never falls
    through to the escalations alone — and that refusal precedes any provider call.

    The escalation judge that duplicates a panel seat's build identity exactly is dropped; the one
    that repeats the panel seat's provider and build but pins a different quantization is kept —
    the chain is five refs, not six — so the fixture pins the de-dup key's granularity (the
    `(provider, build_id, quantization)` build identity), not merely that some de-dup happens.

    The consumer half of the pair is asserted too (FR-AUTHOR-04, ADR-42): `aeh.author`'s own
    source must actually call `panel_for_profile` — an AST call sweep, so a hand-rolled chain
    (or a second, divergent copy of the resolution logic) cannot pass vacuously while the
    dependency itself behaves. Disclosed bet: the sweep matches a call whose target is named
    `panel_for_profile` (direct name or attribute); an aliased import would red here and be the
    reconciliation point at unmark time."""
    panel_for_profile = require(CONF_MODULE, "panel_for_profile", issue="#687")
    from aeh.conf import ConfigurationError
    from aeh.conf.sources import parse_config_document

    cfg = parse_config_document(_DEV_CI_CONFIG, "toml")
    cfg_before = copy.deepcopy(cfg)
    env_before = {k: v for k, v in os.environ.items() if k.startswith("HARNESS_")}
    data_before = _tree_snapshot(tmp_data_dir)
    calls = _provider_spy(monkeypatch)

    first = panel_for_profile(cfg, "dev-ci")
    second = panel_for_profile(cfg, "dev-ci")

    empty_cfg = parse_config_document(_DEV_CI_EMPTY_PANEL_CONFIG, "toml")
    with pytest.raises(ConfigurationError) as refusal:
        panel_for_profile(empty_cfg, "dev-ci")

    expected = [
        ("judge", "openrouter", "meta-llama/llama-3.3-70b-instruct@2024-12-06", None),
        ("judge", "openrouter", "qwen/qwen-2.5-72b-instruct@2024-09-19", None),
        ("judge", "openrouter", "mistralai/mistral-large@2024-11-18", None),
        ("judge", "openrouter", "qwen/qwen-2.5-72b-instruct@2024-09-19", "q4"),
        ("judge", "openrouter", "deepseek/deepseek-v3@2024-12-01", None),
    ]
    problems = []
    if [(r.role, r.provider, r.build_id, r.quantization) for r in first] != expected:
        problems.append(
            f"the chain is not the profile's own panel-then-escalation order de-duplicated by "
            f"build identity: {[(r.role, r.provider, r.build_id, r.quantization) for r in first]}")
    if first != second:
        problems.append("two calls with the same arguments returned different chains (not pure in cfg)")
    if cfg != cfg_before:
        problems.append("panel_for_profile mutated the caller's cfg")
    if {k: v for k, v in os.environ.items() if k.startswith("HARNESS_")} != env_before:
        problems.append("panel_for_profile read or wrote the environment beyond ModelRef resolution")
    if _tree_snapshot(tmp_data_dir) != data_before:
        problems.append("panel_for_profile wrote to the data dir: a cohort or run row moved (CT-CONF-23)")
    if calls:
        problems.append(f"chain resolution reached a provider: {calls}")
    if "panel" not in str(refusal.value) and "judge" not in str(refusal.value):
        problems.append(
            f"the empty-panel refusal does not name the panel or the judge model it refused to "
            f"fall through to: {refusal.value!r}. [When written: an empty [[panel]] raises "
            f"ConfigurationError naming the profile — it never returns the escalations alone "
            f"(CT-CONF-23, test-plan Q-O7).]")
    author_module = require(AUTHOR_MODULE, "AuthoringService", issue="#690")
    consumer_calls = [
        ast.unparse(node.func) for node in ast.walk(ast.parse(package_source(author_module)))
        if isinstance(node, ast.Call)
        and ((isinstance(node.func, ast.Name) and node.func.id == "panel_for_profile")
             or (isinstance(node.func, ast.Attribute) and node.func.attr == "panel_for_profile"))
    ]
    if not consumer_calls:
        problems.append(
            f"aeh.author never calls panel_for_profile: its reasoning chain is built by hand, "
            f"so the profile's own section order and de-dup rule are re-implemented, not cited "
            f"(FR-AUTHOR-04, ADR-42 — the chain comes from M-CONF's panel_for_profile)")
    assert not problems, "; ".join(problems)


# -- TC-REQ-135 ----------------------------------------------------------------------------------


#: Deliberately unparseable by whatever proposal grammar the reasoning steps speak: the steps
#: exhaust the chain and resolve nothing, which is deterministic — the transport discipline is
#: this case's oracle, not the draft's content (see the module docstring's disclosure).
_SCRIPTED_REPLY = (
    "The transport-discipline pairwise case scripts no parseable proposal; exhaust the chain "
    "and resolve every item as instructed by the design (FR-AUTHOR-05, FR-AUTHOR-12)."
)

#: The ASCII token planted in the drafted document's text: the payload assertion — the request
#: carries the extracted document text (FR-AUTHOR-03) — reads for this string on the wire.
DOCUMENT_TEXT_TOKEN = "KEPLER-ORBIT-CONSTANT-7F3"

_DOCUMENT_PAGE = (
    "Physics Test 1 — Forces and Orbits\n"
    "\n"
    f"Reference marker {DOCUMENT_TEXT_TOKEN}.\n"
    "\n"
    "Question 1 (2 points): Name the force that keeps the Moon in orbit around the Earth.\n"
    "\n"
    "Grading: award full credit when the answer names gravity; otherwise no credit.\n"
)


class _RecordingProvider:
    """Wraps the wire provider and records every completion the service asks for, through the
    fixture provider's own `record()` half. Delegation is by `__getattr__` on purpose: if
    M-AUTHOR reaches the provider through any other member, run 2's replay misses loudly rather
    than the wrapper hiding the bypass."""

    def __init__(self, inner, fixture) -> None:
        self._inner = inner
        self._fixture = fixture
        self.complete_calls = 0
        self.models = []

    def complete(self, prompt, model_ref, params):
        self.complete_calls += 1
        self.models.append(model_ref)
        completion = self._inner.complete(prompt, model_ref, params)
        self._fixture.record(prompt, model_ref, params, completion)
        return completion

    def __getattr__(self, name):
        return getattr(self._inner, name)


def test_tc_req_135_every_authoring_call_rides_m_prov(tmp_path, network_guard, monkeypatch):
    """`TC-REQ-135` (`M-AUTHOR` → `M-PROV`, FR-PROV-10, CT-PROV-10, CT-PROV-15), in three runs
    over one recorded session:

    1. **Record.** A draft run against the real `LocalServerProvider` over a capturing
       transport, wrapped so every completion the service asks for is stored through
       `RecordedFixtureProvider.record()` — the exact requests M-AUTHOR makes, structured and
       keyed by the provider's own `request_key`.
    2. **Replay.** The same documents against the bare `RecordedFixtureProvider` over the same
       fixture dir must complete with every call hit: whatever M-AUTHOR asks its provider for,
       it asks through the `InferenceProvider` interface and asks identically on a re-run. A
       call that bypassed the interface, or a request that drifted between runs, misses loudly
       here instead.
    3. **Changed request.** One document's text changed: the first reasoning call now misses,
       and it misses **loudly** — `FixtureMissingError` out of `draft()`, never a stale replay,
       never a silent answer.

    On the wire, the dispatched payloads carry the extracted document text (the token planted
    in the PDF reaches the request), never a credential (the canary sentinel is seeded into
    every credential-bearing variable first) and never a document's raw bytes. A scripted
    transport error is retried **inside** the provider — exactly one extra dispatch for one
    logical call — so M-AUTHOR neither re-implements the provider's retry loop nor sees it.
    And the module's source imports no HTTP client of its own and touches no retention
    reporting: FR-AUTHOR-03 and CT-PROV-15 give both to M-PROV, applied once. The consumer half
    of the M-CONF pair is asserted here too: every dispatched request addresses a model of the
    declared chain and the first addresses the chain head (FR-AUTHOR-04), so a service that
    reasons with a chain of its own cannot pass while the declared one is ignored."""
    AuthoringService, DraftResult, AuthoringSettings = require(
        AUTHOR_MODULE, "AuthoringService", "DraftResult", "AuthoringSettings", issue="#690")
    author_module = require(AUTHOR_MODULE)
    from aeh.prov import FixtureMissingError, TransportError
    from aeh.conf import ModelRef
    from harness.corpora.pdf_writer import typed_document
    from tests.support.conf_builders import (
        EDGE_JUDGE,
        EDGE_JUDGE_2,
        EDGE_JUDGE_3,
        EDGE_TRANSCRIBER,
        SENTINEL_CREDENTIAL,
        seed_credentials,
    )

    seed_credentials(monkeypatch)
    chain = (
        EDGE_JUDGE, EDGE_JUDGE_2, EDGE_JUDGE_3,
        ModelRef(role="judge", provider="ollama", build_id="/models/esc-1.gguf@sha256:aaaa",
                 quantization="q4"),
        ModelRef(role="judge", provider="ollama", build_id="/models/esc-2.gguf@sha256:bbbb",
                 quantization="q4"),
    )
    documents_dir = tmp_path / "documents"
    documents_dir.mkdir()
    doc_a = documents_dir / "test-a.pdf"
    doc_a.write_bytes(typed_document([_DOCUMENT_PAGE]))
    changed_page = _DOCUMENT_PAGE.replace(DOCUMENT_TEXT_TOKEN, "KEPLER-ORBIT-CONSTANT-9E1")
    doc_b = documents_dir / "test-b.pdf"
    doc_b.write_bytes(typed_document([changed_page]))

    transport = WireTransport(
        reply=lambda fields: _SCRIPTED_REPLY,
        script=[TransportError("connection reset on the first authoring call")])
    recordings = tmp_path / "recordings"
    fixture = RecordedFixtureProvider(fixture_dir=recordings)
    recorder = _RecordingProvider(wire_provider(transport), fixture)
    service = AuthoringService(chain=chain, provider=recorder, transcriber=EDGE_TRANSCRIBER,
                               settings=AuthoringSettings())

    dispatches_before, calls_before = transport.attempts, recorder.complete_calls
    result = service.draft([doc_a], tmp_path / "out-1")
    interface_calls = recorder.complete_calls - calls_before
    dispatches = transport.attempts - dispatches_before

    replay = AuthoringService(chain=chain, provider=fixture, transcriber=EDGE_TRANSCRIBER,
                              settings=AuthoringSettings())
    replay_result = replay.draft([doc_a], tmp_path / "out-2")
    with pytest.raises(FixtureMissingError):
        replay.draft([doc_b], tmp_path / "out-3")
    network_guard.assert_no_network()

    serialized = [json.dumps(body) for body in transport.bodies]
    problems = []
    if not isinstance(result, DraftResult) or not isinstance(replay_result, DraftResult):
        problems.append(
            f"fixture: the draft runs did not return DraftResults ({type(result).__name__}, "
            f"{type(replay_result).__name__})")
    if not transport.bodies:
        problems.append("control: the recorded draft run dispatched nothing")
    foreign = sorted({getattr(m, "build_id", str(m)) for m in recorder.models if m not in chain})
    if foreign:
        problems.append(
            f"a dispatched request addressed a model outside the declared chain: {foreign} — "
            f"the service reasons with a chain of its own, not the one its consumer declares")
    if recorder.models and recorder.models[0] != chain[0]:
        problems.append(
            f"the first dispatched request addressed {recorder.models[0]!r}, not the chain head "
            f"{chain[0]!r} (FR-AUTHOR-04: the first judge model answers first)")
    if dispatches - interface_calls != 1:
        problems.append(
            f"the scripted transport error produced {dispatches - interface_calls} dispatch(es) "
            f"beyond the service's own calls ({dispatches} dispatches, {interface_calls} "
            f"interface calls): the provider's retry is not the only retry on the path — "
            f"M-AUTHOR re-implements the provider's transport retry loop (CT-PROV-15)")
    if not any(DOCUMENT_TEXT_TOKEN in body for body in serialized[:1]):
        problems.append(
            "the first dispatched request does not carry the document's extracted text "
            "(FR-AUTHOR-03: the payload carries the document text and the step prompt)")
    leaked = [SENTINEL_CREDENTIAL in body for body in serialized]
    if any(leaked):
        problems.append(
            f"{leaked.count(True)} dispatched request(s) carry the credential sentinel: "
            f"M-AUTHOR sees a key (FR-AUTHOR-03, RISK-124)")
    if any("%PDF-" in body for body in serialized):
        problems.append("a dispatched request carries a document's raw bytes, not extracted text")
    if interface_calls == 0 or not fixture.fixture_dir.exists() or not any(
            fixture.fixture_dir.iterdir()):
        problems.append(
            "control: nothing was recorded through the InferenceProvider interface, so the "
            "replay arm proves nothing — the service never asked the provider to complete "
            "anything")
    source = package_source(author_module)
    tree = ast.parse(source)
    http_imports = sorted({
        alias.name.split(".")[0] if isinstance(node, ast.Import) else (
            (node.module or "").split(".")[0] if node.module else alias.name)
        for node in ast.walk(tree)
        for alias in node.names
        if isinstance(node, (ast.Import, ast.ImportFrom))
        and ((node.module or "") if isinstance(node, ast.ImportFrom) else alias.name).split(".")[0]
        in ("requests", "httpx", "urllib", "urllib3", "http", "socket", "aiohttp", "ssl", "ftplib")
    } & {"requests", "httpx", "urllib", "urllib3", "http", "socket", "aiohttp", "ssl", "ftplib"})
    if http_imports:
        problems.append(
            f"M-AUTHOR imports an HTTP client of its own: {http_imports} (FR-AUTHOR-03, "
            f"CT-PROV-15: the provider is the only egress point)")
    retention_uses = [
        ast.unparse(node) for node in ast.walk(tree)
        if (isinstance(node, ast.Name) and node.id in ("verify_retention", "RetentionReport"))
        or (isinstance(node, ast.Attribute) and node.attr in ("verify_retention", "RetentionReport"))
    ]
    if retention_uses:
        problems.append(
            f"M-AUTHOR touches retention reporting itself: {retention_uses} (CT-PROV-15: the "
            f"provider's retention report is the consumer's input once, never re-implemented)")
    assert not problems, "\n".join(problems)


# -- TC-REQ-136 ----------------------------------------------------------------------------------


def _declared_build_outcome(expected: dict, af: Path) -> str:
    """The fixture's declared per-fixture build outcome — the corpus contract this case bets on.

    Disclosed bet (see the module docstring): the pairwise case reads each fixture's
    `expected.toml` for `[build] outcome = "builds" | "refused"` — the outcome class the tests
    assert. A fixture whose declaration is missing or unknown fails HERE, naming the corpus
    clause, rather than letting the case derive the fixture's outcome from itself: a
    self-derived outcome would make the builds/refused dichotomy vacuous in the weak direction,
    because an incompletely-completed review would silently turn a "builds" fixture into a
    "refused" one and the gate's agreement would never be checked."""
    build = expected.get("build")
    outcome = build.get("outcome") if isinstance(build, dict) else None
    if outcome not in ("builds", "refused"):
        pytest.fail(
            f"{af.name}/expected.toml declares no build outcome this case can assert: found "
            f"{build!r}. The pairwise case bets on [build] outcome = \"builds\" | \"refused\" "
            f"— the outcome class the tests assert (design delta §5.1). The corpus contract "
            f"(#686) must state it, or the case cannot prove the gate agrees with the review "
            f"gate per fixture.")
    return str(outcome)


def _scripted_answers(expected: dict, af: Path) -> dict:
    """The fixture's scripted review answers — the disclosed second corpus bet.

    Read as `[review] answers`, item id → the teacher's plain-language value. A fixture whose
    review completes the draft (AF-07's "review completes to ready") carries the answers here;
    a fixture whose outcome class keeps a placeholder (AF-11's "build refused until filled")
    carries none, and the sentinel survives to the build on purpose."""
    review = expected.get("review")
    if review is None:
        return {}
    if not isinstance(review, dict) or not isinstance(review.get("answers", {}), dict):
        pytest.fail(
            f"{af.name}/expected.toml has a [review] table this case cannot read (bets on "
            f"[review] answers, item id -> value): {review!r}. The corpus contract (#686) owns "
            f"the shape; reconcile the bet in this case's docstring with it.")
    return dict(review.get("answers", {}))


def test_tc_req_136_the_fixture_drafts_face_the_real_build_gate(tmp_path, capsys):
    """`TC-REQ-136` (`M-AUTHOR` → `M-PKG`, FR-PKG-28, CT-PKG-23): every fixture draft in the
    authoring corpus, driven end to end at rung 2 — drafted against the corpus's own recordings,
    review-completed with the fixture's scripted answers, then handed to a real
    `aeh package build` — agrees with the review gate per fixture:

    - a fixture whose review ends *ready* publishes (exit 0, a minted package version), and its
      draft carries no sentinel;
    - a fixture whose declared outcome is *refused* keeps its sentinel, the build exits 1, and
      the refusal names the draft file, the placeholder field and the reason — an incomplete
      draft never publishes, whatever else about it is well-formed.

    The build is the real path (`pipeline.cli.main`, `read_package_spec` → `plan_package` →
    `build_package`), never a re-implementation of the gate (test plan §4.5). The chain and
    transcriber are read from the live-test configuration the corpus was recorded against —
    tests read the config's models, never hard-code them — so the recorded requests key exactly."""
    corpus = require_path(
        REPO_ROOT / "fixtures" / "F-AUTHOR",
        "the authoring fixture corpus AF-01..AF-13 (with expected.toml each and recordings/)",
        issue="#686")
    AuthoringService, DraftResult = require(
        AUTHOR_MODULE, "AuthoringService", "DraftResult", issue="#690")
    ReviewAnswer = require(AUTHOR_MODULE, "ReviewAnswer", issue="#696")
    require_attr(AuthoringService, "review", issue="#696")
    author_module = require(AUTHOR_MODULE)
    from aeh.conf import ModelRef
    from aeh.conf.sources import parse_config_document
    from aeh.pipeline import cli as pipe_cli

    config_path = REPO_ROOT / "docs" / "live-tests" / "config" / "live-test.dev-ci.toml"
    cfg = parse_config_document(config_path.read_text(encoding="utf-8"), "toml")
    section = cfg["profiles"]["dev-ci"]
    chain = tuple(section["panel"]) + tuple(
        ModelRef(role=t["role"], provider=t["provider"], build_id=t["build_id"],
                 quantization=t.get("quantization"))
        for t in section.get("escalation_judge", ()))
    fixture_dirs = sorted(p for p in corpus.iterdir() if p.is_dir() and p.name.startswith("AF-"))
    assert fixture_dirs, f"control: no AF-* fixture directories under {corpus}"

    service = AuthoringService(
        chain=chain, provider=RecordedFixtureProvider(fixture_dir=corpus / "recordings"),
        transcriber=section["transcriber"], settings=author_module.AuthoringSettings())

    built, refused = [], []
    for af in fixture_dirs:
        expected = tomllib.loads((af / "expected.toml").read_text(encoding="utf-8"))
        outcome = _declared_build_outcome(expected, af)
        answers = [ReviewAnswer(item_id=str(item), value=str(value))
                   for item, value in _scripted_answers(expected, af).items()]
        result = service.draft(sorted(af.glob("*.pdf")), tmp_path / af.name / "draft")
        assert isinstance(result, DraftResult), (
            f"fixture: {af.name}'s draft run returned {type(result).__name__}, not DraftResult")
        review = service.review(result.draft_path, answers=answers)
        draft_text = result.draft_path.read_text(encoding="utf-8")
        sentinels = sorted(set(re.findall(r"<<PLACEHOLDER: ([^>]+)>>", draft_text)))
        data_dir = tmp_path / af.name / "data"
        for sub in ("packages", "cohorts", "blobs"):
            (data_dir / sub).mkdir(parents=True)
        capsys.readouterr()  # drop the draft/review chatter; the build's output is the oracle
        code = pipe_cli.main(
            ["package", "build", "--data-dir", str(data_dir), "--spec", str(result.draft_path)])
        captured = capsys.readouterr()

        if outcome == "builds":
            problems = []
            if sentinels:
                problems.append(
                    f"{af.name} is declared to build but its completed review left "
                    f"sentinel(s) {sentinels} — the scripted [review] answers (#686's bet) did "
                    f"not complete the draft, so the gate's agreement is never exercised")
            if review.ready is not True:
                problems.append(
                    f"{af.name} is declared to build but review did not end ready: remaining "
                    f"{getattr(review, 'remaining', None)}")
            if code != 0:
                problems.append(
                    f"{af.name}'s ready draft did not build: exit {code}, stderr "
                    f"{captured.err.strip()!r}")
            else:
                try:
                    report = json.loads(captured.out)
                except ValueError:
                    problems.append(
                        f"{af.name}'s build printed no JSON package report: "
                        f"{captured.out.strip()!r}")
                else:
                    if not report.get("package_version"):
                        problems.append(
                            f"{af.name}'s build report mints no package version: {report!r}")
            if problems:
                refused.append((af.name, "; ".join(problems)))
            else:
                built.append(af.name)
        else:  # declared "refused"
            problems = []
            if not sentinels:
                problems.append(
                    f"{af.name} is declared refused but its draft carries no "
                    f"<<PLACEHOLDER: …>> sentinel: the gate would have nothing to refuse, so "
                    f"the per-fixture oracle is vacuous")
            if code != 1:
                problems.append(
                    f"{af.name}'s sentinel-carrying draft was not refused: exit {code}, stdout "
                    f"{captured.out.strip()!r}")
            else:
                if Path(result.draft_path).name not in captured.err:
                    problems.append(
                        f"{af.name}'s refusal does not name the draft file "
                        f"{Path(result.draft_path).name}: stderr {captured.err.strip()!r}")
                if "PLACEHOLDER" not in captured.err:
                    problems.append(
                        f"{af.name}'s refusal does not name the placeholder sentinel or its "
                        f"reason: stderr {captured.err.strip()!r}")
                unmatched = [f for f in sentinels if f not in captured.err]
                if sentinels and len(unmatched) == len(sentinels):
                    problems.append(
                        f"{af.name}'s refusal names none of the draft's placeholder fields "
                        f"{sentinels}: stderr {captured.err.strip()!r}")
            if problems:
                refused.append((af.name, "; ".join(problems)))
            else:
                built.append(af.name)

    assert built == [af.name for af in fixture_dirs], (
        f"the build gate disagreed with the declared per-fixture outcomes: "
        f"{refused}. [When written: the corpus (#686), the authoring surface (#690) and the "
        f"review walk (#696) have not landed, so this case cannot run yet; each corpus-shape "
        f"bet is disclosed in the module docstring and fails naming its clause.]")