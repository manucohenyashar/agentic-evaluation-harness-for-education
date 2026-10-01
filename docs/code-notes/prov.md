# `aeh.prov`: design notes

These notes were the docstring of `src/aeh/prov.py` before it was split into the `aeh/prov/` package. They record why the module is built the way it is, with the requirement, contract and issue IDs behind each decision. The package's own `__init__.py` has the short overview; comments in the code that say "see the module docstring" refer to this file.

---

`M-PROV` — Inference Provider Abstraction (design §3.2).

One `InferenceProvider` interface, and the only path by which a model call leaves the harness.
A caller holding this module holds *"text in, text out, accounted for"* and no knowledge
whatever of which backend answered (`CT-PROV`).

Scope of this file today
------------------------
`M-PROV` ships across four stories. **#18** (this file's first commit) lands `FR-PROV-01`,
`FR-PROV-02`, `FR-PROV-13`, `NFR-PROV-02`, `NFR-PROV-05`: the interface, the boundary types,
the canonical request encoding that makes payload passthrough byte-identical, and
`RecordedFixtureProvider` — the fast tier's deterministic transport.

Still to land, and deliberately absent rather than stubbed:

| Story | What it adds |
|---|---|
| #19 | `FR-PROV-06`/`-07`/`-08` — the retry loop, 429 backpressure, the no-fallback rule. The taxonomy below is *declared* here so #19 does not have to reshape it (a breaking change, per §3.2 Compatibility) |
| #20 | `FR-PROV-04`/`-05`/`-09`/`-12` — resolved-build comparison, `BuildChangedError`, `actual_cost` accumulation, the six run counters |
| #21 | `FR-PROV-03`/`-10`/`-11`/`-14` — `LocalServerProvider`, `OpenRouterProvider`, the import-graph assertion, retention verification, pseudonymized payloads |

`RecordedFixtureProvider` is here rather than with #21 because it is the only implementation
that reaches no network, and #18's own acceptance criteria — *"returns a fully-populated
`Completion`"*, *"captured at the caller and on the wire"* — are unassertable against a
Protocol with no implementation behind it. `tests/support/impl.py` names #18 as the blocker
for `tests/unit/prov/test_recorded_fixture_provider.py` for the same reason.

Why the fixture provider is not a test double
---------------------------------------------
Test plan §4.2 calls it *"a shipped implementation, not a test fake"*, and RISK-37 is why:
almost every case in the plan runs against it, so if it drifts from the contract the live
providers keep — stops raising what they raise, populates a field they leave `None` — the fast
tier stays green while describing a system that does not exist. That is a **critical** risk
whose symptom is a passing suite. Every decision below that looks over-careful for a fixture
reader is paying that risk down.

Decisions this file fixes, that the design underdetermines
----------------------------------------------------------
Recorded here rather than in a commit message because `TS-05` (#22), `TS-06` (#23), `TS-07`
(#24) and `TS-59` (#25) are written **against whatever this module ships**, and a signature
they have to guess is a suite that asserts the wrong thing.

| Decision | Choice | Forced by |
|---|---|---|
| `PromptPayload`'s shape | `fields: tuple[tuple[str, str], ...]` — ordered, named, values opaque | Named but unspecified in §3.2; `TS-00` constructs it this way, and `CT-PROV-05` forbids reordering, so a mapping would have been the wrong type |
| `SamplingParams`' shape | `temperature` plus four optional knobs, all part of the request key | Named but unspecified in §3.2 |
| `record()` | The recording half of `FR-PROV-10`, on the fixture implementation only | §4.4 regenerates `F-RECORDED` nightly, so a recording path must exist; **nothing in the design names it**. Raised as a finding on the PR |
| Request key | `sha256` over a **length-framed** encoding — never a separator join | Injectivity. The same defect the reviewer found in `compute_panel_build_ref` on #4; here it cannot be closed by refusing control characters, because payload values are submission prose |
| The key covers payload, `ModelRef` **and every** `SamplingParams` field | Derived from `dataclasses.fields`, so a knob added later changes the key | `FR-PROV-10` says "the fully-assembled request"; `TC-PROV-14`'s five mutations each kill one naive key |
| `request_key` streams into the hasher | No buffer holding the assembled request is ever materialized | `NFR-PROV-02`: no per-call copy of the invariant prefix |
| `record()` refuses a non-null `cost` | `ValueError`, naming `CT-PROV-03` | Fixture ⇒ `cost is None`. Storing a cloud cost would make the canonical double contradict the clause every consumer tests against (RISK-37); normalizing it silently would hide the same thing |
| The **reader** refuses one too | `FixtureMissingError`, not a silent `None` | The writer is loud and the reader is the path every fast-tier test runs; normalizing on read would make the rule silent exactly where it matters |
| Every unusable fixture file raises inside the taxonomy | Bad JSON, a wrong `schema`, a moved `key`, a missing or ill-typed field: all `FixtureMissingError` | `CT-PROV-07` is what a caller catches. A bare `JSONDecodeError` out of a hand-edited recording is a hole in it, and §4.4 regenerates `F-RECORDED` nightly |
| One payload encoder, shared | `_emit_payload`, used by both `payload_bytes` and `request_key` | Two copies of one encoding drift: once #21 derives the wire body from `payload_bytes`, a change to it must move the key |
| A non-finite `temperature`/`top_p` | Refused at construction | It records and then never matches itself (`nan != nan`), so the recording would exist on disk and miss forever |
| `latency_ms` is replayed, never measured | The stored `Completion` is returned unchanged | `TC-PROV-13` compares the whole value by equality; a measured latency makes replay non-deterministic |
| A fixture file stores the **request** as well as the response | Verified on read; a mismatch is a miss | Turns a key collision into a loud `FixtureMissingError` instead of a stale answer — the exact RISK-37 failure `TC-PROV-14` exists to prevent |
| Error taxonomy | Seven **siblings** under a neutral `ProviderError`; all declared, one raised here | `CT-PROV-07` names six and asserts retryability *per error*; siblings keep every "exact exception type" oracle discriminating, and reshaping the hierarchy later is a breaking change |
| `Capabilities` resolved once, in `__init__` | Never re-read from the environment per call | `CT-PROV-04`: declared, not discovered, and "stable for the life of the run" |
| Fixture declares `supports_prefix_cache=True` | It replays the recorded backend's prefix accounting | Declaring `False` would send consumers down a different code path against the double than against a live backend — verbatim the drift `NFR-PROV-01` forbids |
| `estimate_cost` uses the *implementation's* declared `cost_per_token` | `CallPlan` carries call count and per-call token budgets only | §3.2's signature takes no `ModelRef`; `FR-PROV-09` says "planned call count and per-call token budgets" |

The four seams (`CLAUDE.md`)
----------------------------
1. **Headless driver** — this is a library; every operation is a plain synchronous call and
   nothing here touches a console.
2. **Deterministic transport** — `RecordedFixtureProvider`, landing in the same commit as the
   interface whose dependency it stands in for. It reaches no network on any code path.
3. **Env-gated knobs** — `HARNESS_FIXTURE_DIR` and `HARNESS_FIXTURE_MAX_CONCURRENCY`, both
   read once at construction. `HARNESS_RETRY_MAX` and `HARNESS_BACKOFF_BASE_MS` arrive with
   #19, which owns the loop that reads them.
4. **Stage-level observability** — `Completion` carries the per-call detail next to the text
   (`tokens_in`, `tokens_out`, `latency_ms`, `resolved_build`, `cached_prefix_tokens`), and
   the per-call DEBUG line of `CT-PROV-14` is emitted here. It names metadata only: payload
   values are student work, so no field value reaches a log line (`CT-PROV-13`).
