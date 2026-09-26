# Detailed Design Delta: Jev-Powered Scoring with Confidence-Gated LLM Fallback

**Source:**
- The user's directive (2026-09-25). Jev must power the test graders and evaluators. When Jev's confidence is not above 80%, grading falls back to the original LLM path. The rubrics are expressed in Jev's Choice / Score / Noul object model. The connected configuration uses Jev on OpenRouter. The local configuration uses OpenJev. Each of the two gets its own provider. "Everything stays the same, the only thing that changes is the grading and evaluation engine. All the bias protection, orchestration and the overall system flow stay the same."
- `docs/design/detailed-design.md` v1.4 (the "base design").
- `docs/design/fix_gaps_detailed_design_plan.md` v1.5.1-delta (the "gap delta"). This document applies on top of both.
- The external Jev / OpenJev documentation listed in §1.2.

**Code baseline validated against:** `main` @ `fb12d1e`, `src/aeh/*.py` (§6).

**Version:** 1.7.1-delta  **Date:** 2026-09-25  **Status:** Draft, for review before `/create-test-plan`.
**Author:** `/detailed-design-generator`, delta mode.

## Revision history

| Version | Date | Change | Author |
|---|---|---|---|
| 1.7.1-delta | 2026-09-25 | **User decisions on OpenJevSmall** (resolves Q-J12, Q-J13 and Q-J14): <br>• `openjev-small` defaults to a **0.85** confidence threshold, still configurable (FR-CONF-21, CT-CONF-19). <br>• **4B v5 is the build, and 2B v5 is the fallback build**, chosen at configuration time and never switched at runtime (FR-CONF-27). <br>• The documented prompt-injection weakness is **accepted**, and FR-CONFORM-12 remains as a measurement. | user decision |
| 1.7-delta | 2026-09-25 | **OpenJevSmall: a third decision provider for machines too small for OpenJev** (user request). The user asked whether the community model `AlexWortega/openjev` (`qwen3.5-4b-nli-v5`) solves the co-residency problem. **Verdict: plausible, not proven** (§3.11.1). <br>• **Fits on paper:** 9.1 GB bf16 against OpenJev's ≥ 15 GB. <br>• **Unproven where it matters:** it has only a Python/CUDA serving path, no Apple (MLX) build, uncalibrated confidence, and a documented prompt-injection weakness. <br>• **What the design does:** it adds the provider as an **opt-in, gated** engine. That covers `OpenJevSmallLocalProvider`, a loopback shim outside `src/aeh`, per-engine residency, and a manual acceptance gate on the reference hardware. It also adds a live injection-robustness measurement. <br>• **Correction:** FR-CONF-23's `discrete-gpu` co-residency assumption contradicted HLD §8.1 ("exactly one model in VRAM") and is fixed. <br>• **IDs:** FR-PROV-30…37, NFR-PROV-09, FR-CONF-27/28, NFR-JUDGE-10, FR-CONFORM-12, NFR-SYS-16, CT-PROV-26…28, CT-CONF-21, CT-CONFORM-16, ADR-27. | `/detailed-design-generator` (user request) |
| 1.6.1-delta | 2026-09-25 | **Corrections from `/create-test-plan` (`jev_test_plan.md` Q-26…Q-38)**, all additive to 1.6: <br>• **No shipped config file exists** at `fb12d1e` (the CLI takes `--config`, `pipeline.py:1049`). FR-CONF-18 now requires a new reference file, `config/harness.example.toml`. <br>• The eligibility token ratio is now **frozen** into `DecisionEngine` (`token_bytes_ratio`), which resolves the contradiction with §1.3 (FR-CONF-17/21, FR-JUDGE-26, FR-ORCH-36, CT-CONF-18). <br>• **Nine `Requires` rows added** for edges that relied on new clauses without declaring it (§3.4–§3.9). <br>• FR-JUDGE-36's denominator is stated. FR-JUDGE-29's number format is pinned. FR-JUDGE-31 no longer counts engine malformations against the LLM judge. NFR-STATS-06's below-minimum behaviour is stated. <br>• **CT-JUDGE-30** (security): the inventory never enters a model prompt. <br>• FR-PIPE-14 emits no engine tag when the engine is off, so it no longer conflicts with NFR-SYS-14. | `/detailed-design-generator` (test-plan findings) |
| 1.6-delta | 2026-09-25 | Adds a **decision engine** (Jev) to panel scoring. New `DecisionProvider` surface in `M-PROV` with two separate live implementations: `JevOpenRouterProvider` for the connected configuration and `OpenJevLocalProvider` for the local one. `RecordedFixtureProvider` gains a `decide` door. `M-CONF` freezes the engine in `RunConfig`. `M-JUDGE` gets the rubric→Jev mapping, the confidence gate, the seat rule and pre-screen persistence. There are supporting deltas on `M-ORCH`, `M-AGG`, `M-GRADE`, `M-STATS`, `M-PIPE`, `M-CONFORM` and `M-STORE`, plus 7 ADRs (ADR-20…ADR-26). No existing ID is renumbered. Amendments are explicit and classified under base §4.7. | `/detailed-design-generator` |

---

## 1. Scope & purpose

This is a **delta**, not a replacement. It specifies everything an implementer needs to make Jev the first scoring engine for panel verdicts. Jev's answer stands when it is confident. When it is not, the verdict comes from the unchanged LLM judge.

### 1.1 What changes, what does not, and one correction to the brief

**Changes:** the engine that produces a panel verdict.
- Today every score unit sends one assembled prompt to one LLM judge (`ScoringWorker.dispatch`, `judge.py:1832`).
- After this delta, an eligible unit first asks Jev a set of typed questions derived from the **same** assembled `ScoringRequest`.
- If the gate confidence is strictly above the threshold (default 0.80), the Jev answer becomes the verdict.
- Otherwise the unit continues down today's LLM path, byte for byte.

**Stays the same.** Every item below is asserted by a clause in this delta, not just hoped for:
- Isolation (CT-JUDGE-02/03).
- The numeral-free rubric surface.
- Untrusted-content fencing.
- Citation verification.
- Median-band aggregation and ordinal α.
- The confidence inversion caps (CT-AGG-05).
- Escalation 1→3→5 and the random arm.
- Review sampling, grade policy and the run lifecycle.
- The provider-error pause path.
- The "one judgment, one sample" rule.

**Correction to the brief: `M-GRADE` does not grade with a model.** The brief names `M-GRADE` next to `M-JUDGE` as a grader to be powered by Jev. `M-GRADE` makes no model call at all:
- `grade.py:17-18` says it "runs with no network, no provider and no fixtures".
- It is the one module whose determinism is structural.
- It applies the teacher's declared grade policy to `criterion_score` rows arithmetically.

So there is no LLM grading inside `M-GRADE` to replace. The rubric-level *evaluation* the brief means happens in `M-JUDGE`, which produces verdicts, and in `M-AGG`, which turns verdicts into scores. The `M-GRADE` delta (§3.6) is therefore one engine-blindness guarantee: a grade depends on the score rows only, never on which engine produced the verdicts beneath them. Adding a model to `M-GRADE` would break CT-GRADE-07's no-imputation property and its determinism, with nothing to gain.

**Out of scope:**
- Test cases (`/create-test-plan`) and issues (`/plan-to-issues`). §5 names affected existing tests as reconciliation input only.
- Replacing any model call outside panel scoring. §7 Q-J8 lists the candidates: extraction, transcription, setup and synthesis are generative tasks Jev cannot do; `M-INGEST` V4 and `M-INTEG` could use Nouls later.
- Images in Jev state. Submissions reach `M-JUDGE` as canonical Markdown, and Jev state here is text only.

### 1.2 Jev: the facts this design builds on

Every design element below uses only the facts in this table. Anything not in it is marked `Assumption:`.

| Fact | Value | Source |
|---|---|---|
| What Jev is | A "System One" decision model: unstructured state in, typed probabilistic answers out. No text, no reasoning trace, no explanation. | TypeSafe blog; OpenRouter guide |
| Request | `{model, state: string\|object\|array, questions: {<key>: Question}}` | docs.typesafe.ai/api; OpenJev model card |
| **Choice** question | `{type:"choice", instructions, criteria: {option: description\|null}}`, up to 255 options (OpenJev: 52 per pass) | docs.typesafe.ai/api; OpenJev card |
| **Score** question | `{type:"score", instructions, criteria: [ordered level descriptions]}`, 2–10 levels | docs.typesafe.ai/api |
| **Noul** question | `{type:"noul", instructions, criteria?: {true: desc, false: desc}}` | docs.typesafe.ai/api |
| Choice answer | `{type:"choice", choice, probabilities: {option: p}, confidence}` | docs.typesafe.ai/api |
| Score answer | `{type:"score", score: float, legend: {"0": level, …}, probabilities: {"0": p, …}, confidence}`. `score` is the probability-weighted position. | docs.typesafe.ai/api |
| Noul answer | `{type:"noul", noul: p_true}`. **No confidence field.** | docs.typesafe.ai/api; community guides |
| Confidence statistic | `(count × peak − 1) / (count − 1)`, where `peak` is the maximum probability. On OpenRouter, `confidence` is *optional* on Choice and Score answers. | MarkTechPost guide (quoting TypeSafe); OpenRouter Decisions API reference |
| Response envelope | `{model, answers, usage: {input_tokens, output_tokens, cost?}, id?, provider?}` | OpenRouter Decisions API reference |
| OpenRouter endpoints | `POST https://openrouter.ai/api/alpha/decisions` (Decisions API; accepts `provider`, `session_id`, `trace`, `user`) and `POST https://openrouter.ai/api/v1/systemone` (TypeSafe-SDK compatible) | OpenRouter Jev guide + API reference |
| OpenRouter model ids | `typesafe/jev-1.13` (pinned), `~typesafe/jev-latest` (floating alias) | OpenRouter Jev guide |
| OpenRouter limits | 32,000-token context (state + questions); input-token billing; output tokens free; `usage.cost` in USD | OpenRouter Jev guide |
| OpenRouter errors | 400, 401, 402 (insufficient credits), 403, 429, 500, 524 (timeout) | OpenRouter Decisions API reference |
| TypeSafe direct errors | 401, 422, 429, 529 (overloaded) | docs.typesafe.ai/api |
| OpenJev | 27B open-weights decision model, served by vLLM plus a "shim" HTTP server exposing `POST /v1/systemone` with the same request shape. 16,384-token prompt limit; 52 options per question; one image per request; weights CC BY-NC 4.0, code Apache 2.0. Formats: bf16 (~54 GB), FP8 (~29 GB), MLX 8-bit (~27 GB), MLX 4-bit (~15 GB), GGUF. | huggingface.co/openjev/openjev |
| Latency claims | Jev: 70–500 ms end to end. OpenJev on one H100: ~80 ms per short-text question, ~210 ms median for a web step. | TypeSafe blog; OpenJev card |
| Order sensitivity | OpenJev: "Shuffle the option order and the answer changes in 2.3% of cases" | OpenJev card |
| **OpenJevSmall** (community, not TypeSafe) | `AlexWortega/openjev`, subfolder `qwen3.5-4b-nli-v5`. It is a 3-way NLI **cross-encoder** (`Qwen3_5ForSequenceClassification`, labels contradiction/entailment/neutral), **not** a generative or System One model. There are also `qwen3.5-2b-nli-v5`, `qwen3.5-0.8b-nli-v5` and `qwen3.5-4b-nli-v5-nvfp4`. MIT licence. | HF model card; `config.json` |
| OpenJevSmall weights | 4B v5: `model.safetensors` **9.08 GB**, `dtype: bfloat16`. The nvfp4 build targets NVIDIA FP4 hardware. **No MLX or GGUF build is published.** | HF file listing; `config.json` |
| OpenJevSmall serving | A Python wrapper (`code/openjev_decide.py`, `OpenJev.from_pretrained(...).decide(state, questions)`) over transformers, or SGLang (`serve_sglang.sh`, a `/classify` endpoint returning raw logits). There is **no `/v1/systemone` HTTP server**. SGLang is tested on an RTX A6000 only. | HF card; `code/` listing |
| OpenJevSmall decision semantics | Every option becomes one hypothesis, `The answer to "{instr}" is {label}: {crit}`, scored in **its own forward pass**. The distribution is P(entailment) normalised over the options. It returns `{"noul": p}` or `{"probabilities": {label: p}}`, with **no confidence field** and no ordinal model for `score`. It is order-invariant (0/231 label changes when options are shuffled). | `openjev_decide.py`; HF card |
| OpenJevSmall context | The encoder window is ~8k tokens (`WINDOW_CHARS = 24_000`). A longer state is **split into windows and scored by the maximum entailment over windows** ("a claim supported by any window is supported by the document"). | `openjev_decide.py` |
| OpenJevSmall quality | JevBench v1.2 public (231 items): **0.866** (README) or **0.814** (RESULTS-v5; hard tier 0.622). "Jev 1.13 0.87" on the same items. MNLI 0.896/0.899. Its training mix includes the test splits of MMLU/ARC/GSM8K/HellaSwag/WinoGrande/GPQA, whose numbers are therefore "meaningless". | HF card; `RESULTS-v5.md` |
| OpenJevSmall weaknesses | Prompt injection: "one adversarial line in the state ... drops accuracy on 150 JevBench items from 0.833 to 0.467" (README); **0.436** under fake policy updates (RESULTS-v5). | HF card; `RESULTS-v5.md` |

**Two properties shape the design more than the rest:**
- **Jev's answers to identical input are, at minimum, highly correlated.** This is an *inference*, not a sourced fact: each answer is one forward pass with a readout of option scores, and nothing is sampled (OpenJev card, "Technical Mechanism"). No source promises bit-exact determinism, and the design does not need it. Two panel seats sending Jev the same request would not be independent judges, and that alone is what §3.3 and ADR-21 build on.
- **Jev writes no text.** It cannot produce `cited_spans` or `evidence_assessment` the way an LLM judge does. §3.3 derives both from typed answers over spans already present in the request.

### 1.3 Conventions

- **IDs** continue from the highest ID in use across the base design, the gap delta, `src/` and `tests/` at `fb12d1e`. They are append-only. This delta's first new IDs are:

  | Module | First new FR | First new NFR | First new CT |
  |---|---|---|---|
  | M-PROV | FR-PROV-16 | NFR-PROV-06 | CT-PROV-17 |
  | M-CONF | FR-CONF-17 | — | CT-CONF-17 |
  | M-JUDGE | FR-JUDGE-22 | NFR-JUDGE-06 | CT-JUDGE-21 |
  | M-ORCH | FR-ORCH-36 | — | CT-ORCH-29 |
  | M-AGG | FR-AGG-18 | — | CT-AGG-22 |
  | M-GRADE | FR-GRADE-19 | — | CT-GRADE-21 |
  | M-STATS | FR-STATS-25 | NFR-STATS-06 | CT-STATS-24 |
  | M-PIPE | FR-PIPE-11 | — | CT-PIPE-08 |
  | M-CONFORM | FR-CONFORM-10 | — | CT-CONFORM-15 |
  | ADRs | ADR-20 | | |

- **Migrations.** Next free versions at `fb12d1e` (`store.py:1479-1483`: Package 12, Cohort 27, Durable 11) are **Cohort 28** and **Cohort 29**. If another migration lands first, take the next free number. Each migration bumps `COMPLETE_SCHEMA_VERSIONS` and the `CLAUDE.md` migration-chain paragraph in the same change.
- **Declared SQL only.** Every new statement is a module-level `Statement` in the owner's `*_STATEMENTS` registry (FR-STORE-08 / SEC-15). Every new `tx.execute` site joins `KNOWN_EXECUTE_SITES`, and the SEC-15 census line numbers move with it.
- **Knobs** are named `HARNESS_JEV_*` and refuse invalid values, per `CLAUDE.md` seam 3. **Exception, stated deliberately:** the knobs that decide *which verdict counts* are read **once, at run start**, into `RunConfig`, instead of at call time. These are the threshold and the citation cutoff. A call-time read would let an environment change mid-run alter which engine grades which student, which is exactly what CT-CONF-14 forbids. Operational knobs (timeouts, URLs, alert rates) stay call-time.
- **"Decision engine"** is the generic term in type and column names. "Jev" is the one engine this delta ships. The seam allows a second engine without a schema change.
- `Assumption:` marks any number or choice the sources above do not supply.

---

## 2. Module inventory (delta)

| Module ID | Name | Change | Depends on (delta) |
|---|---|---|---|
| M-PROV | Inference Provider Abstraction | **New `DecisionProvider` surface.** (1.7: a third live implementation, `OpenJevSmallLocalProvider`, plus its loopback shim under `tools/`, §3.11.) `JevOpenRouterProvider` and `OpenJevLocalProvider` (separate classes, separate transports, separate config), `RecordedFixtureProvider.decide`, and `decision_provider_for`. | unchanged, plus external: OpenRouter Decisions API, OpenJev shim |
| M-CONF | Deployment Profile & Run Configuration | `RunConfig.decision_engine` (13th field). Profile→engine provider binding. Run-start freezing of the threshold. | unchanged |
| M-JUDGE | Panel Scoring | Rubric→Jev question mapping, confidence gate, seat rule, Jev verdict construction, pre-screen persistence, `decision_engine_metrics`. | unchanged (already depends on `M-PROV`, `M-CONF` via run config) |
| M-ORCH | Run Orchestrator | Decision engine in `panel_config` (work identity), cost plan includes decision calls, decision-provider counters flushed to `run_metrics`. | unchanged |
| M-AGG | Aggregation | Refuses a panel carrying two decision-engine verdicts. Arithmetic is engine-blind. | unchanged |
| M-GRADE | Grading | Engine-blindness clause only (no model, no code path change). | unchanged |
| M-STATS | Validation Statistics | Per-engine partition of `judge_signals` and of blind-label agreement. Decision-engine gate calibration report. | unchanged |
| M-PIPE | Run Composition | Builds the decision provider, injects it into `ScoringWorker`, reports decision-engine outcomes in the stage trace. | + `M-PROV.decision_provider_for` |
| M-CONFORM | Backend Conformance | Runs the frozen fixture set through both Jev backends and reports divergence. | unchanged |
| M-STORE | Persistence | Cohort migrations 28/29 (owned by `aeh.judge`), pin bump. | unchanged |

**No module is added.** The decision engine is an engine *inside* `M-JUDGE`'s boundary, reached only through `M-PROV`'s seam. It is not a new stage. Making it a stage would change the orchestration the brief says must not change (ADR-20).

---

## 3. Per-module design deltas

### 3.1 Module: `M-PROV` — delta · the decision surface and two separate Jev providers

**Responsibility (delta).** Provide a second provider surface, `DecisionProvider`: typed questions in, typed probabilistic answers out, accounted for. It has two live implementations, one per deployment family, plus the recorded-fixture double. `M-PROV` remains the **only egress point** (CT-PROV-15): no other module imports an HTTP client or names a Jev endpoint.

**Does not own.** Which questions to ask, how answers become a verdict, or the gate. Those belong to `M-JUDGE`. **`M-PROV` still never substitutes one engine for another** (CT-PROV-08 is unchanged): a failing `decide` raises, and choosing to ask the LLM instead is `M-JUDGE`'s decision on a *confidence* outcome, never `M-PROV`'s on a *failure* (ADR-20, ADR-26).

**Functional requirements (new)**

| ID | Requirement | Traces to | Phase |
|---|---|---|---|
| FR-PROV-16 | The module shall expose a `DecisionProvider` protocol: `decide(request: DecisionRequest, model_ref: ModelRef) -> Decision`, `capabilities(model_ref) -> DecisionCapabilities`, `estimate_cost(plan: CallPlan) -> CostEstimate`, `verify_retention(model_refs) -> RetentionReport`. `decide` is synchronous and blocking, and one call is one HTTP request. | User directive; R27 | 1 |
| FR-PROV-17 | `DecisionRequest` shall be a closed, frozen value: `state: str` and `questions: tuple[DecisionQuestion, ...]`, where each question is exactly one of `ChoiceQuestion(key, instructions, options: tuple[tuple[str, str \| None], ...])`, `ScoreQuestion(key, instructions, levels: tuple[str, ...])`, `NoulQuestion(key, instructions, when_true: str \| None, when_false: str \| None)`. Construction shall raise `DecisionRequestError` when: a key is not unique; a key fails `^[a-z][a-z_]{0,31}$` (no digits, so a key can never inject a numeral into the request, see FR-JUDGE-03); a Choice has fewer than 2 or more than `capabilities.max_choice_options` options; a Score has fewer than 2 or more than 10 levels; the question count exceeds `capabilities.max_questions`; or `state` is empty. | Jev object model (§1.2) | 1 |
| FR-PROV-18 | `Decision` shall carry `answers: Mapping[str, DecisionAnswer]` (one per question key, no more, no fewer), `tokens_in`, `tokens_out`, `latency_ms`, `resolved_build`, `cost: Decimal \| None`. Each answer is exactly one of: `ChoiceAnswer(choice, probabilities, confidence, confidence_source)`; `ScoreAnswer(score, probabilities: tuple[float, ...] indexed by level, confidence, confidence_source)`; `NoulAnswer(p_true, confidence, confidence_source)`. | §1.2 | 1 |
| FR-PROV-19 | **Confidence normalization.** For Choice and Score, `confidence` shall be the response's `confidence` when present (`confidence_source="reported"`). Otherwise it is `(n × max(p) − 1) / (n − 1)` over that answer's probabilities (`"derived"`). For Noul, which reports none, it shall be `|2 × p_true − 1|` (`"derived"`). This is the same statistic with `n = 2` over `{p, 1 − p}`. A reported confidence outside `[0, 1]` is a malformed response. | §1.2 confidence statistic | 1 |
| FR-PROV-20 | **Structural validation** of every response, raising `MalformedResponseError` (retryable per CT-PROV-06) when any of these fail: the answer key set equals the question key set; each answer's `type` equals its question's type; Choice `probabilities` keys equal the option set; Score `probabilities`/`legend` cover exactly indices `0…L−1` and `legend[i]` equals `levels[i]`; every probability lies in `[0, 1]`; each distribution sums to 1 within `1e-3`; `noul` lies in `[0, 1]`. The module shall not repair, renormalize or reorder any answer. | CT-PROV-06; FR-JUDGE-09's "refuse, don't repair" posture | 1 |
| FR-PROV-21 | `JevOpenRouterProvider` shall be the connected implementation. It POSTs to `HARNESS_JEV_OPENROUTER_URL` (default `https://openrouter.ai/api/alpha/decisions`, ADR-24) with `Authorization: Bearer $OPENROUTER_API_KEY`. The body is `{model: <wire model>, state, questions, provider: {order: [<pinned upstream>], allow_fallbacks: false, data_collection: "deny", zdr: true}, session_id: <run_id>}`. The wire model is the `build_id` with any `openrouter/` prefix and `@<pin>` suffix removed (e.g. `typesafe/jev-1.13`). It shall never send a floating alias (`~…-latest`). | User directive (connected → OpenRouter); FR-PROV-11/14 | 1 |
| FR-PROV-22 | `OpenJevLocalProvider` shall be the local implementation, a **separate class** with its own base URL (`HARNESS_OPENJEV_BASE_URL`, default `http://127.0.0.1:3000`). It POSTs `{model: $HARNESS_OPENJEV_MODEL_NAME (default "openjev"), state, questions}` to `<base>/v1/systemone`. It shall refuse at construction a base URL whose host is not loopback unless `HARNESS_OPENJEV_ALLOW_REMOTE=true`. `edge-local` payloads never leave the machine (base §3.2 security). | User directive (local → OpenJev); R4 | 1 |
| FR-PROV-23 | **Error mapping**, both live implementations. Transport failure, timeout, 500, 524 and 529 → `TransportError` (retryable). 429 → `RateLimitedError` (honour `Retry-After`, FR-PROV-07). 400 and 422 → `DecisionRequestRejectedError`: **not retryable**, raised on first occurrence, carrying the status and at most 512 bytes of the error body with no request bytes. 401 and 403 → `ConfigurationError`. 402 → `ProviderUnavailableError` (credits exhausted pauses the run, it does not degrade it). A body failing FR-PROV-20 → `MalformedResponseError`. Retry budget and jitter are the existing `HARNESS_RETRY_MAX` / `HARNESS_BACKOFF_BASE_MS` (CT-PROV-06). | CT-PROV-06/07 | 1 |
| FR-PROV-24 | **Build identity.** `JevOpenRouterProvider` shall set `resolved_build` from the response's `model` (then `provider`) field and feed it to the existing `BuildWatch`, so a served build that differs from the run-start build raises `BuildChangedError` (FR-PROV-05). `OpenJevLocalProvider` shall, at run start (`verify_build`), read the vLLM server's `GET <vllm>/v1/models` `root`/`id` and compare its weights identity with the `ModelRef`'s `@sha256:` digest, raising `BuildChangedError` on mismatch. Per call, `resolved_build` is that verified identity. Assumption: the shim echoes only the served name, so per-call drift is detectable only by re-probing, which the provider does every `HARNESS_OPENJEV_BUILD_PROBE_EVERY` calls (default 500). | FR-PROV-04/05; CT-CONF-03 | 1 |
| FR-PROV-25 | `RecordedFixtureProvider` shall implement `DecisionProvider.decide`. Fixtures are keyed by a hash over the scheme tag `aeh.prov/decision-key/1`, the `ModelRef` and the canonical encoding of the full `DecisionRequest` (state bytes, then questions in order with every field). An unknown key raises `FixtureMissingError` with no network call. `record(...)` writes decision fixtures under the same `HARNESS_FIXTURE_DIR` with schema `aeh.prov/decision-fixture/1`. The fixture double shall raise every FR-PROV-23 error type when a fixture document declares it, so consumers can test fallback and pause paths hermetically. | CT-PROV-10; seam 2 | 1 |
| FR-PROV-26 | `decision_provider_for(model_ref, **seams) -> DecisionProvider` shall be the only construction path. `provider == "openrouter-jev"` → `JevOpenRouterProvider`; `"openjev"` → `OpenJevLocalProvider`; `"fixture"` → `RecordedFixtureProvider`. Any other value → `ConfigurationError`. | NFR-PROV-05 | 1 |
| FR-PROV-27 | `DecisionCapabilities` shall be declared per implementation (CT-PROV-04 posture): `max_context_tokens` (OpenRouter 32,000; OpenJev `min(16384, HARNESS_OPENJEV_MAX_MODEL_LEN)`), `max_choice_options` (255; OpenJev 52), `max_questions` (Assumption: 64 on both, pending Q-J3), `cost_per_input_token` (OpenRouter from `HARNESS_JEV_COST_PER_MTOK_IN`, default `0.042` USD per MTok (Assumption, from the TypeSafe list price); OpenJev and fixture `None`), `deterministic: True`. | FR-PROV-02 | 1 |
| FR-PROV-28 | `verify_retention` on `JevOpenRouterProvider` shall confirm zero-retention routing for the decision model by the same fail-closed rule as FR-PROV-14. For `cloud-hosted`, the run-start retention gate covers the panel **and** the decision model. An unconfirmed decision model raises `RetentionPolicyError` and the run does not start. `OpenJevLocalProvider.verify_retention` confirms trivially only for a loopback base URL. | FR-PROV-14; R4, R31 | 1 |
| FR-PROV-29 | Decision calls shall accumulate in the existing `RunCountersTracker` under new names: `decision_calls`, `decision_tokens_in`, `decision_transport_retries`, `decision_rate_limited_calls`, `decision_actual_cost`. `actual_cost` stays the sum of both surfaces, so `M-ORCH`'s ceiling sees one figure. | FR-PROV-09/12; seam 4 | 1 |

**Interfaces**

```python
# aeh/prov.py (additions)
class DecisionProvider(Protocol):
    def decide(self, request: DecisionRequest, model_ref: ModelRef) -> Decision: ...
    def capabilities(self, model_ref: ModelRef) -> DecisionCapabilities: ...
    def estimate_cost(self, plan: CallPlan) -> CostEstimate: ...
    def verify_retention(self, model_refs: Sequence[ModelRef]) -> RetentionReport: ...

@dataclass(frozen=True)
class ChoiceQuestion:  key: str; instructions: str; options: tuple[tuple[str, str | None], ...]
@dataclass(frozen=True)
class ScoreQuestion:   key: str; instructions: str; levels: tuple[str, ...]      # ordered, low → high
@dataclass(frozen=True)
class NoulQuestion:    key: str; instructions: str; when_true: str | None = None; when_false: str | None = None
DecisionQuestion = ChoiceQuestion | ScoreQuestion | NoulQuestion

@dataclass(frozen=True)
class DecisionRequest: state: str; questions: tuple[DecisionQuestion, ...]

@dataclass(frozen=True)
class ChoiceAnswer: choice: str; probabilities: Mapping[str, float]; confidence: float; confidence_source: Literal["reported", "derived"]
@dataclass(frozen=True)
class ScoreAnswer:  score: float; probabilities: tuple[float, ...]; confidence: float; confidence_source: Literal["reported", "derived"]
@dataclass(frozen=True)
class NoulAnswer:   p_true: float; confidence: float; confidence_source: Literal["derived"] = "derived"

@dataclass(frozen=True)
class Decision:
    answers: Mapping[str, ChoiceAnswer | ScoreAnswer | NoulAnswer]
    tokens_in: int; tokens_out: int; latency_ms: int
    resolved_build: str
    cost: Decimal | None                 # null on edge-local and fixture (CT-PROV-03 posture)

class DecisionRequestError(ValueError): ...           # construction-time, caller defect
class DecisionRequestRejectedError(ProviderError): ... # 400/422 from the engine; not retryable

def decision_provider_for(model_ref: ModelRef, **seams) -> DecisionProvider: ...
class JevOpenRouterProvider(_BaseLiveProvider): ...    # connected configuration
class OpenJevLocalProvider(_BaseLiveProvider): ...     # local configuration
```

Both live classes reuse `_BaseLiveProvider`'s retry loop (`dispatch_with_retries`), `Transport`, `Clock`, `ConcurrencyGovernor`, `BuildWatch` and `RunCountersTracker`. Only the body encoder, the response parser, the URL and the error table differ. The two are separate classes, not one class with a mode flag, per the user's directive and NFR-PROV-05.

**Data flow.** `M-JUDGE` builds a `DecisionRequest` from a `ScoringRequest` (§3.3). It calls `decide` on the provider bound for the run. The provider encodes, dispatches, retries only per CT-PROV-06, validates (FR-PROV-20), normalizes confidence (FR-PROV-19) and returns a `Decision`. Counters accumulate in memory and `M-ORCH` flushes them (§3.4).

**Non-functional requirements (new)**

| ID | Category | Requirement |
|---|---|---|
| NFR-PROV-06 | Compatibility | `JevOpenRouterProvider`, `OpenJevLocalProvider` and `RecordedFixtureProvider.decide` shall be substitutable with only `RunConfig.decision_engine` differing. The `F-JEV` conformance fixture set (§3.9) passes against each. |
| NFR-PROV-07 | Performance | Encoding plus parsing plus validation shall add under 5 ms per `decide` call above the engine's own latency, for a request of 20 questions and 8,000 state tokens. Assumption, the CT-PROV-12 figure reused. |
| NFR-PROV-08 | Security | A `decide` request body carries `student_ref` only, never a student name (NFR-PROV-04), and no credential appears in any log line, exception or `Decision` (CT-PROV-13). |

**Configuration (new).** Call-time unless stated:
- `HARNESS_JEV_OPENROUTER_URL`
- `HARNESS_JEV_COST_PER_MTOK_IN` (default `0.042`)
- `HARNESS_JEV_TIMEOUT_S` (default 10)
- `HARNESS_OPENJEV_BASE_URL` (default `http://127.0.0.1:3000`)
- `HARNESS_OPENJEV_MODEL_NAME` (default `openjev`)
- `HARNESS_OPENJEV_VLLM_URL` (default `http://127.0.0.1:8000/v1`, for the build probe)
- `HARNESS_OPENJEV_MAX_MODEL_LEN` (default 16384)
- `HARNESS_OPENJEV_ALLOW_REMOTE` (default false)
- `HARNESS_OPENJEV_BUILD_PROBE_EVERY` (default 500)
- `HARNESS_OPENJEV_TIMEOUT_S` (default 20)
- `OPENROUTER_API_KEY` (existing)

**Contract delta** (`CT-PROV`, v1.0 → **v1.1**, additive)

| ID | Kind | Clause (assertable) | Consumers |
|---|---|---|---|
| CT-PROV-17 | surface | `decide(request, model_ref) -> Decision` is synchronous and blocking, and one call is one engine request. `capabilities`, `estimate_cost` and `verify_retention` make no engine call. The module starts no threads for it. | `M-JUDGE`, `M-ORCH`, `M-CONFORM` |
| CT-PROV-18 | data | A returned `Decision` has exactly one answer per question key, typed as its question. Every probability lies in `[0, 1]`, and each distribution sums to 1 ± 1e-3. `ScoreAnswer.probabilities[i]` is the probability of `levels[i]`. Every answer carries a `confidence` in `[0, 1]` and its `confidence_source`. A response violating any of this never reaches the caller (FR-PROV-20). | `M-JUDGE` |
| CT-PROV-19 | behaviour | Confidence is normalized by FR-PROV-19's single statistic. A Noul's confidence is always `|2p − 1|`, and a Choice or Score without a reported confidence gets the derived statistic. Consumers never see a missing confidence. | `M-JUDGE`, `M-STATS` |
| CT-PROV-20 | error | `DecisionRequestRejectedError` (400/422) is **not retried** and surfaces on the first occurrence. `MalformedResponseError` surfaces after the retry budget. `TransportError`/`RateLimitedError` are retried internally first. `ProviderUnavailableError` (incl. 402) and `BuildChangedError` are terminal for the run. A failed `decide` leaves no state. | `M-JUDGE`, `M-ORCH` |
| CT-PROV-21 | behaviour | A successfully parsed `Decision` is never re-requested by this module (CT-PROV-06 extended to `decide`). The module never substitutes another engine or model for a failing decision model (CT-PROV-08 extended to `decide`). | `M-JUDGE`, `M-ORCH` |
| CT-PROV-22 | behaviour | `JevOpenRouterProvider` and `OpenJevLocalProvider` are distinct classes selected only by `decision_provider_for` on `ModelRef.provider`. `OpenJevLocalProvider` sends nothing to a non-loopback host unless `HARNESS_OPENJEV_ALLOW_REMOTE=true`. `JevOpenRouterProvider` never sends a floating model alias and always sends `allow_fallbacks: false`. | `M-CONF`, `M-CONFORM` |
| CT-PROV-23 | behaviour | The fixture `decide` is keyed by a hash of the full `DecisionRequest` and `ModelRef`, raises `FixtureMissingError` for an unknown request without any network call, and reproduces CT-PROV-18/20 exactly, including raising declared error types. | `M-CONFORM`, test suites |
| CT-PROV-24 | observe | Decision counters `decision_calls`, `decision_tokens_in`, `decision_transport_retries`, `decision_rate_limited_calls`, `decision_actual_cost` exist by those names and are included in `actual_cost`. | `M-ORCH`, ops |
| CT-PROV-25 | security | For `cloud-hosted`, the decision model passes the same fail-closed retention gate as the panel before the first dispatch of either (FR-PROV-28). Decision request bodies carry `student_ref` only. | `M-CONF`, `M-ORCH` |

*Requires (delta)*

| Depends on | Clauses relied on | What this module assumes |
|---|---|---|
| `M-CONF` | CT-CONF-17, CT-CONF-18 | The decision `ModelRef` is resolved and frozen for the run, and its provider name matches the profile |
| OpenRouter Decisions API | (external) | The request/response schema in §1.2; `provider` preferences honoured; `Retry-After` on 429 |
| OpenJev shim + vLLM | (external) | `POST /v1/systemone` with the §1.2 schema; vLLM `GET /v1/models` exposes the served weights path |

*Compatibility.* Additive: a new surface, new errors on the new surface only, new counters. The existing `InferenceProvider` surface, its clauses and its fixture keys are untouched: `KEY_SCHEME` stays `aeh.prov/request-key/1`, and decision keys use their own scheme tag, so no recorded completion fixture moves. The canonical double for consumers is `RecordedFixtureProvider.decide`, and it must reproduce CT-PROV-18/19/20.

---

### 3.2 Module: `M-CONF` — delta · the decision engine is part of "which grader is this run"

**Functional requirements (new)**

| ID | Requirement | Traces to | Phase |
|---|---|---|---|
| FR-CONF-17 | `RunConfig` shall gain a thirteenth field, `decision_engine: DecisionEngine \| None`. `DecisionEngine` is frozen: `model: ModelRef` (role `"decision"`), `confidence_threshold: Decimal`, `cite_threshold: Decimal`, `max_citation_questions: int`, `token_bytes_ratio: int`. It is non-null iff the resolved `HARNESS_DECISION_ENGINE` is `jev`. | User directive; CT-CONF-14 | 1 |
| FR-CONF-18 | `HARNESS_DECISION_ENGINE` shall be required for every profile, with domain `{jev, off}`. Absence raises `ConfigurationError` naming the key. There is no silent default, because a default here selects a backend (CT-CONF-11). The repository shall ship a reference per-profile config file, `config/harness.example.toml` (FR-CONF-13 format; new in this delta, since none exists at `fb12d1e`), whose `edge-local`, `cloud-hosted` and `dev-ci` sections set `HARNESS_DECISION_ENGINE = "jev"` and a pinned `HARNESS_JEV_BUILD`. It parses under `parse_config_document`, and every section resolves under `resolve_run_config` given its credentials. Its `edge-local` section names `HARNESS_HARDWARE_PROFILE = "unified-large"`, because `unified-small` refuses Jev (FR-CONF-23, Q-J4). | User directive; CT-CONF-11 | 1 |
| FR-CONF-19 | **Profile binding.** *(`edge-local` row amended in 1.7 by FR-CONF-27 to `openjev` or `openjev-small`.)* When the engine is `jev`, `decision_engine.model.provider` shall be `openjev` for `edge-local` and `openrouter-jev` for `cloud-hosted` and `dev-ci`. Any other pairing raises `BackendMismatchError`. `fixture` is accepted on any profile only when `HARNESS_FIXTURE_DIR` is set, which is the test tier's existing condition. | User directive (connected/local split) | 1 |
| FR-CONF-20 | The decision `ModelRef` shall satisfy `is_resolved()` by the existing rules (CT-CONF-03). For `edge-local`, a weights path plus quantization plus `@sha256:` digest (e.g. `/models/openjev-FP8@sha256:…`, quantization `fp8`, or the MLX 4-bit build with `q4`). Otherwise a provider-pinned slug (e.g. `openrouter/typesafe/jev-1.13@2026-09-01`). A floating tag (`~typesafe/jev-latest`, `:latest`) is refused. The build is read from `HARNESS_JEV_BUILD`. | FR-CONF-03 | 1 |
| FR-CONF-21 | `confidence_threshold` shall be read once, at resolution, from `HARNESS_JEV_CONFIDENCE_THRESHOLD` (domain `[0.50, 1.00)`, refused outside it). When the knob is unset, the default depends on the decision provider: **`0.85` for `openjev-small`** (1.7.1, user decision: its probabilities are normalised entailment, not calibrated confidence) and `0.80` for every other provider. An explicitly set value applies to any provider, including `openjev-small`. `cite_threshold` from `HARNESS_JEV_CITE_THRESHOLD` (default `0.50`, domain `(0, 1)`). `max_citation_questions` from `HARNESS_JEV_MAX_CITATION_QUESTIONS` (default 16, domain 1–26, limited by the one-letter span labels of FR-JUDGE-24). `token_bytes_ratio` from `HARNESS_JEV_TOKEN_BYTES_RATIO` (default 3, domain 1–8). It moves the eligibility boundary and therefore which engine grades a unit, so it is frozen like the others. All four are frozen for the run and rehydrated identically on resume (FR-CONF-15). | User directive ("> 80%"); CT-CONF-14 | 1 |
| FR-CONF-22 | `compute_panel_build_ref` shall include the decision engine's build identity and its four frozen values **when `decision_engine` is non-null**. When it is null, the computation and its output are byte-identical to today. | FR-ORCH-01 work identity | 1 |
| FR-CONF-23 | **Residency.** *(Amended in 1.7 by FR-CONF-28: residency is now declared per decision provider, and the `discrete-gpu` value below is corrected.)* `HardwarePolicy` shall gain `decision_coresident`. `edge-local` with engine `jev` on a hardware profile that does not admit the configured decision provider raises `ConfigurationError`, naming the profile and the admitted alternatives (`openjev-small` where admitted, and `HARNESS_DECISION_ENGINE=off`). For `openjev`, Assumption: `unified-large` admits it; `unified-small` does not (the OpenJev MLX 4-bit build is ~15 GB beside a ~18 GB 30B-class judge on a 32 GB machine, HLD §8.1); `discrete-gpu` does not (HLD §8.1: "exactly one model in VRAM at a time" on a 16–24 GB card; 1.6 wrongly assumed it did). | HLD §8.1 residency; FR-CONF-06 | 1 |
| FR-CONF-24 | The R31 consent gate (FR-CONF-12 family) shall treat a `cloud-hosted` decision engine as remote dispatch of student work, exactly as it treats the panel. A cohort whose consent class forbids remote processing cannot start a run whose decision engine is `openrouter-jev`. | R31 | 1 |
| FR-CONF-25 | `format_profile_banner` shall add one line, `DECISION_ENGINE: <provider>:<build> threshold=<t>` or `DECISION_ENGINE: off`, so an operator sees which engine grades. | FR-CONF-16 | 1 |
| FR-CONF-26 | `ProfileSummary` (FR-CONF-09, the grader identity a teacher sees under a grade, CT-CONSOLE-10) shall gain `decision_engine: BuildSummary \| None` plus the frozen threshold. `to_canonical_json` shall **omit the key when it is `None`**, so an engine-off run's stored and logged summary stays byte-identical to today (TC-CONF-17's differential and NFR-SYS-14). | FR-CONF-09; NFR-SYS-14 | 1 |

**Interfaces**

```python
@dataclass(frozen=True)
class DecisionEngine:
    model: ModelRef                   # role "decision"; provider ∈ {"openjev", "openrouter-jev", "fixture"}
    confidence_threshold: Decimal     # accept iff gate_confidence > this (strict)
    cite_threshold: Decimal           # a span is cited iff its Noul p_true >= this
    max_citation_questions: int
    token_bytes_ratio: int            # eligibility estimator divisor (FR-JUDGE-26)

class RunConfig:                      # 12 existing fields, then:
    decision_engine: DecisionEngine | None
```

`ModelRole` gains `"decision"`. `rehydrate_run_config` reads the engine back from the run row's `provider_config` JSON under key `decision_engine`. The row column already exists, so no migration is needed. A run created before this delta has no key and rehydrates `decision_engine=None`, which keeps a resumed legacy run grading exactly as it started.

**Contract delta** (`CT-CONF`, v1.x → **v2.0**, breaking: the `RunConfig` field set changes)

| ID | Kind | Clause (assertable) | Consumers |
|---|---|---|---|
| CT-CONF-02 (amended) | data | …`RunConfig` carries exactly the **thirteen** fields listed in Interfaces… `decision_engine` is non-null iff `HARNESS_DECISION_ENGINE = jev`. *(Amendment: field count 12 → 13 and the added iff. Every other sentence is unchanged.)* | `M-ORCH`, `M-JUDGE`, `M-AGG`, `M-CONSOLE`, `M-PIPE` |
| CT-CONF-17 | data | When non-null, `decision_engine.model` satisfies `is_resolved()`, has role `decision`, and its provider is `openjev` or `openjev-small` (1.7) iff `edge-local`, `openrouter-jev` iff `cloud-hosted`/`dev-ci`, or `fixture` under the test tier (FR-CONF-19/20). | `M-PROV`, `M-JUDGE`, `M-PIPE` |
| CT-CONF-18 | behaviour | `confidence_threshold`, `cite_threshold`, `max_citation_questions` and `token_bytes_ratio` are fixed at resolution and never re-read during the run. An environment change after run start does not alter them, and a resumed run rehydrates them unchanged. | `M-JUDGE`, `M-ORCH` |
| CT-CONF-19 | config | `HARNESS_DECISION_ENGINE` has no default, and absence raises. `HARNESS_JEV_CONFIDENCE_THRESHOLD` defaults to `0.85` when the decision provider is `openjev-small` and `0.80` otherwise, in `[0.50, 1.00)`. An explicit value overrides the default for every provider. Out-of-domain values raise, never clamp. | operator |
| CT-CONF-20 | behaviour | `panel_build_ref` and `ProfileSummary.to_canonical_json()` for a run with `decision_engine = None` are byte-identical to their pre-delta values. With an engine, both differ from the same panel without one. | `M-ORCH`, `M-STATS`, `M-CONSOLE` |

CT-CONF-14 (a safety property) is **unchanged and upheld**: there is still no operation that changes a run's grader. The engine joins the frozen identity.

*Compatibility.* **Breaking** (v2.0). `CT-CONF-C02`'s set-equality test must move from 12 to 13 fields in the same change. That breaking edit is the clause working. Re-verify every `M-CONF` consumer in base §4.7 plus `M-PIPE`. Every literal `RunConfig(...)` construction in `tests/support` gains `decision_engine=None` (or an engine), and `resolve_run_config` fixtures gain `HARNESS_DECISION_ENGINE`.

---

### 3.3 Module: `M-JUDGE` — delta · the rubric in Jev's object model, the gate, and the seat rule

**Responsibility (delta).** For each score unit, the module:
1. Decides whether the unit is the cell's **decision seat** and whether the decision engine can answer it (eligibility).
2. Asks the engine typed questions derived from the unchanged `ScoringRequest`.
3. Accepts the answer as the verdict only when the gate confidence is strictly above the frozen threshold.
4. Otherwise produces the verdict exactly as today.

Exactly one verdict is persisted per unit, as today.

#### 3.3.1 The rubric → Jev object mapping

A rubric in this system is a set of criteria. Each has an ordered, even band set of 2–6 bands (CT-PKG-04), each band with a descriptor. The criterion is judged against extracted evidence spans. One score unit is one criterion × one submission × one judge (CT-JUDGE-03). The Jev request for one unit is:

| Rubric element | Jev primitive | Key | Construction |
|---|---|---|---|
| The criterion's band set: which band does the work meet? | **Score** | `band` | `levels` = one string per declared band, in `band_ordinal` ascending order (CT-PKG-04: lowest first), each `"<band>: <descriptor>"` (or `"<band>"` with no descriptor), the same text `_render_bands` renders. `instructions` = `JEV_BAND_INSTRUCTIONS`, a static, numeral-free sentence: "Which band description does the work inside the untrusted block meet for the criterion stated above? Judge only the work inside the block." |
| `evidence_sufficient` | **Noul** | `evidence_sufficient` | Static `instructions`: "The extracted evidence is sufficient to place the work in a band for this criterion." `when_true`/`when_false` are static descriptions mirroring the LLM reply field's meaning. |
| `cited_spans`: which extracted spans support the placement? | **Noul** per span | `cite_a`, `cite_b`, … | One Noul per span in `request.evidence` (the criterion's own spans, in evidence order), labelled `a`…`z`. `instructions`: "Evidence span [<label>] inside the untrusted block is relevant evidence for the criterion." The instruction carries only the label, never span bytes, so no student text leaves the untrusted block. |
| Categorical criteria (unordered options) | **Choice** | — | **Not used in this delta.** Every judged criterion has an *ordered* band set, and ordering is contract (CT-PKG-04). A Choice would discard the order and let adjacent-band confusion look like a distant one. Choice exists in the `M-PROV` surface for future engines and for Q-J8's candidates. |

**Why Score and not Choice for bands** (ADR-22). Score keeps the ordinal structure that α and median aggregation rely on (FR-AGG-01/04). The band is the **argmax** of `ScoreAnswer.probabilities`, never `round(score)`. `score` is a probability-weighted mean position, and averaging on an ordinal scale is precisely what FR-AGG-02 forbids everywhere else in the system. `score` is recorded for observability only.

**The `state`.** `decision_fields(request)` is a new pure render, a sibling of `prompt_fields`, reusing its helpers. It is a string of these fields in this fixed order:
1. `jev_directive`: static. It declares the untrusted block to be data to be judged, never instructions, as `_DIRECTIVE` does, minus the reply-format sentence.
2. `criterion` (`_render_criterion`).
3. `question` (`_render_question`).
4. `exemplars` (`_render_exemplars`).
5. `submission`: `_render_submission`, with each own-evidence line prefixed by its label `[span a]`, `[span b]`, … inside the fence.

Bands are **not** repeated in `state`. They are the Score's levels. Fields are joined as `"### <name>\n<value>"` with blank-line separators. Everything before `submission` is the invariant prefix, byte-identical across a batch (CT-JUDGE-08), which is what OpenJev's vLLM prefix caching and OpenRouter's billing both benefit from.

#### 3.3.2 Eligibility, the seat rule, and the gate

**The seat rule** (ADR-21). A cell's **decision seat** is the score unit whose `judge` is the build id of the **frozen** run panel's first member, `RunConfig.panel[0]`. It is deliberately not the run row's `panel_config.arms[0]`, which the OOM-drop path may rewrite mid-run (`orch.py:1210`); a rewrite would otherwise promote an LLM arm into a second decision seat. Base and random-arm units for the same judge share one row (origin is not a `work_id` input), and escalation additions never re-add an arm the pair already carries, so that one unit per cell is always a base unit. Only that unit may be answered by the decision engine. Every other arm is LLM-only. This covers the other base arms of a 3- or 5-panel, escalation arms, random-arm widenings and `escalation-arm-<k>` extensions.

The reason: Jev's answers to identical input are at least highly correlated (§1.2), and every arm of a cell receives the identical request (CT-JUDGE-03). If several seats ran Jev, a widened panel would be close to three copies of one answer. That gives α ≈ 1, confidence rises, and the cell auto-accepts, which is exactly the outcome escalation exists to prevent. The rule keeps every panel's independence exactly what it is today: the base seat is either Jev or the seat-0 LLM, and every other arm is whatever LLM judge it is today. The rule adds no Jev-to-Jev correlation. It does not claim more diversity than today's panel and escalation-arm derivation provide (`pipeline.judge_for`).

**Eligibility.** A decision-seat unit is *eligible* unless one of these holds. Checks run in this order and the first failing reason is recorded:

| Reason | Condition |
|---|---|
| `engine_off` | `run_config.decision_engine is None` (recorded nowhere; the path is simply today's) |
| `not_seat` | Not the decision seat (recorded nowhere) |
| `no_band_set` | The criterion declares no band set (the bands field is conditional in `prompt_fields`) |
| `band_count` | `len(bands) < 2` or `> 10`. Unreachable under CT-PKG-04 (2–6) and kept as a guard |
| `too_many_spans` | `len(request.evidence) > max_citation_questions` (Assumption: citing only some spans would under-report citations, so the unit goes to the LLM instead) |
| `context` | `estimate_tokens(state + questions) > 0.9 × capabilities.max_context_tokens`, where `estimate_tokens = ceil(utf8_bytes / engine.token_bytes_ratio)` (default 3, frozen at run start per FR-CONF-21; Assumption: a deliberately pessimistic ratio; no tokenizer is imported). **Never truncate.** |
| `question_count` | `2 + len(evidence) > capabilities.max_questions` |

An ineligible unit goes **directly** to the LLM path, and its reason is recorded (FR-JUDGE-28).

**The gate.** For an eligible unit's `Decision`:

```
c_band        = answers["band"].confidence                        # CT-PROV-19
c_sufficient  = answers["evidence_sufficient"].confidence         # = |2p − 1|
gate          = min(c_band, c_sufficient)
argmax        = indices of max(answers["band"].probabilities)
accept  iff   gate > run_config.decision_engine.confidence_threshold     # strict: 0.80 falls back
         and  len(argmax) == 1
         and  every cited span passes _refuse_unverified_citations
```

Citation Nouls are **not** in the gate. They select which verified spans the verdict cites, and a low-confidence citation simply is not cited (FR-JUDGE-25). Including them would make an unambiguous band on a long answer fall back because one marginal span was uncertain.

**Strictness.** The brief says "confidence higher than 80%", then "when confidence drops below 80% fall back". The gate is strictly `> 0.80`, so exactly 0.80 falls back. This is the conservative reading of the overlap, and it is a single-character knob if the user wants `≥`.

#### 3.3.3 Functional requirements (new)

| ID | Requirement | Traces to | Phase |
|---|---|---|---|
| FR-JUDGE-22 | `ScoringWorker` shall accept an optional `decision_provider: DecisionProvider` and read `decision_engine` from the bound run config. With either absent, `dispatch` behaves byte-identically to today. The fixture key, prompt bytes and strike semantics do not change. | User directive: "everything stays the same" | 1 |
| FR-JUDGE-23 | `is_decision_seat(unit, run_config) -> bool` shall be a pure function returning true iff `unit.judge == run_config.panel[0].build_id` (the frozen panel, not the mutable `panel_config` row). If `panel[0]` is dropped by the OOM path, its remaining units are simply never dispatched, and no other arm becomes a seat. `dispatch` shall consult the decision engine **only** for a decision seat. | ADR-21; FR-AGG-09; §7.1 | 1 |
| FR-JUDGE-24 | `decision_request(request: ScoringRequest, engine: DecisionEngine) -> DecisionRequest` shall be pure and derived only from the `ScoringRequest`. It builds `state` by §3.3.1's `decision_fields`, a Score `band` over the declared bands in ordinal-ascending order, a Noul `evidence_sufficient`, and one Noul `cite_<label>` per own-evidence span (labels `a`…`z` in evidence order). It adds no field the `ScoringRequest` whitelist does not carry. | CT-JUDGE-02; User directive (rubric → Choice/Score/Noul) | 1 |
| FR-JUDGE-25 | **Isolation and numeral scan carry over.** `assert_isolated` shall run on the `ScoringRequest` before derivation, as today. The FR-JUDGE-03 numeral scan shall run over the rendered `DecisionRequest`: `state`'s rubric-surface fields at rubric strictness and `submission` at content strictness, exactly as for `prompt_fields`, plus every question's `instructions`, `levels`, `when_true` and `when_false` at rubric strictness. A violation raises `IsolationViolation` and nothing is dispatched. | FR-JUDGE-01/02/03; CT-JUDGE-03 (safety property) | 1 |
| FR-JUDGE-26 | **Eligibility** shall be computed by the pure `decision_eligibility(request, engine, capabilities) -> Eligible \| Ineligible(reason)` over §3.3.2's table, in its order. An ineligible unit shall go straight to the LLM path, and the input shall never be truncated. | Seam 4; §1.2 limits | 1 |
| FR-JUDGE-27 | **Gate.** `gate_decision(decision, request, engine) -> Accepted(result) \| BelowGate(gate, reason)` shall be pure and implement §3.3.2: `gate = min(c_band, c_sufficient)`; accept iff `gate > confidence_threshold` and the band argmax is unique. `reason ∈ {below_threshold, argmax_tie}`. | User directive (80%) | 1 |
| FR-JUDGE-28 | **Verdict construction from an accepted Decision.** The result has these fields: `band` is the declared band at the argmax index, and `band_ordinal` is that index. `self_confidence = c_band`. `evidence_sufficient = p_true ≥ 0.5` of the `evidence_sufficient` Noul. `cited_spans` are the own-evidence spans whose `cite_*` Noul has `p_true ≥ cite_threshold`, in evidence order, as the *identical* span documents from `request.evidence`. `uncited = not cited_spans`. `evidence_assessment` is the FR-JUDGE-29 inventory. `resolved_build = decision.resolved_build`. `latency_ms = decision.latency_ms`. `scoring_engine = "decision"`. `integrity_flags` includes `DECISION_ENGINE_INVENTORY`. | CT-JUDGE-04/06 | 1 |
| FR-JUDGE-29 | **Engine-generated inventory.** `evidence_assessment` for a decision-engine verdict shall be deterministic, non-prose text: `engine: <build>; cited: span a, span c; band probabilities: <band>=<p>, …; sufficiency: <p>`, every probability rendered with exactly four decimal places (`f"{p:.4f}"`). It lists cited span labels by name, so FR-JUDGE-10's span-reference check passes on substance, not on phrasing. It shall never be presented as judge reasoning, and consumers identify it by the `DECISION_ENGINE_INVENTORY` flag and `scoring_engine`. If no span is cited it reads `cited: none` and the verdict is uncited (FR-JUDGE-12 unchanged). | FR-JUDGE-10/12; CT-JUDGE-16 | 1 |
| FR-JUDGE-30 | **Citation verification.** Every span in an accepted decision-engine verdict's `cited_spans` shall pass `_refuse_unverified_citations` before the verdict exists. A failure turns the outcome into `BelowGate(reason="citation_unverified")` and the unit proceeds to the LLM path. It is not a strike, since the engine cited a span the extractor supplied. | FR-JUDGE-17 (iv); FR-INTEG-01 | 1 |
| FR-JUDGE-31 | **Fallback.** For a decision seat whose outcome is `Ineligible`, `BelowGate`, `DecisionRequestRejectedError` (reason `rejected`) or `MalformedResponseError` after the provider's budget (reason `malformed`), `dispatch` shall run today's LLM path **unchanged**: the same `prompt_fields` payload, judge `ModelRef`, sampling parameters, strike budget, FR-JUDGE-10 amendment and `JudgmentError`. It shall record `scoring_engine = "llm"`. The below-gate decision is never merged with, averaged into or shown to the LLM judge, and no field of the LLM request changes because a pre-screen happened. A malformed or rejected engine response is **not** counted in the arm judge's `judge_contract_violations` (FR-JUDGE-21), since it is not that LLM judge's violation. It is visible as `decision_malformed`/`decision_rejected` instead. | User directive (fallback); CT-JUDGE-02/11 | 1 |
| FR-JUDGE-32 | **Outage is not a confidence outcome.** `RateLimitedError`, `ProviderUnavailableError` and `BuildChangedError` from `decide` shall propagate exactly as from `complete` (FR-JUDGE-19 / CT-JUDGE-19): no strike, nothing persisted, and the dispatch pass waits or pauses the run (FR-ORCH-30). `dispatch` shall **not** fall back to the LLM on these. | ADR-26; CT-PROV-08; R1 | 1 |
| FR-JUDGE-33 | **One pre-screen per unit.** Before calling `decide`, `dispatch` shall read the unit's `decision_prescreen` row (FR-JUDGE-34). If one exists, it shall reuse the stored outcome and not call the engine again. An `accepted` row rebuilds the verdict via FR-JUDGE-28 from stored answers. Any other outcome goes straight to the LLM path. A redelivered unit (CT-ORCH-04) therefore never samples the engine twice. | CT-PROV-06 / CT-JUDGE-11 spirit; NFR-PIPE-01 | 1 |
| FR-JUDGE-34 | **Pre-screen persistence.** Every decision-seat unit that reaches the engine, or is found ineligible, shall write one `decision_prescreen` row (Cohort migration 28), `INSERT OR IGNORE` on `work_id`, in its own transaction **before** the LLM path starts or the verdict is persisted. Columns: `work_id` PK; `run_id`; `submission_id`; `criterion_id`; `engine_build`; `outcome ∈ {accepted, below_gate, ineligible, rejected, malformed}`; `reason`; `gate_confidence REAL NULL`; `band_confidence REAL NULL`; `sufficiency_p REAL NULL`; `argmax_band TEXT NULL`; `band_probabilities TEXT NULL` (JSON array by ordinal); `band_score REAL NULL`; `cite_probabilities TEXT NULL` (JSON object label→p); `threshold REAL NOT NULL`; `tokens_in INTEGER`; `latency_ms INTEGER`; `cost TEXT NULL`. The row carries no points value and no LLM output. | Seam 4; FR-JUDGE-33 | 1 |
| FR-JUDGE-35 | **Verdict provenance.** The `verdict` row shall gain `scoring_engine TEXT CHECK (scoring_engine IN ('llm','decision'))` and `engine_build TEXT` (Cohort migration 29). `persist` writes both on every row. A `NULL` `scoring_engine` (a pre-delta row) is read as `'llm'`. `StoredVerdict` and `verdicts_for` gain `scoring_engine`. `judge_id` stays the arm's identity, as today. | FR-JUDGE-11/18; FR-AGG-18 | 1 |
| FR-JUDGE-36 | `decision_engine_metrics(handle, run_id) -> DecisionEngineMetrics` shall read `decision_prescreen` and return: per criterion and overall, counts by outcome and by ineligibility reason; accepted rate; fallback rate (`below_gate + rejected + malformed`) / prescreens, where **prescreens counts every `decision_prescreen` row, `ineligible` included**; gate-confidence histogram (10 bins); decision latency p50/p95. It shall also return two alert flags. `decision_fallback_rate_high` fires when fallback rate > `HARNESS_JEV_FALLBACK_ALERT_RATE` (default 0.50) over at least `HARNESS_JEV_ALERT_MIN_PRESCREENS` (default 50) prescreens. `decision_requests_rejected` fires when any `rejected` outcome exists, because a rejected request is a harness defect, not a hard question. | Seam 4; CT-JUDGE-16 | 1 |
| FR-JUDGE-37 | **Adversarial parity.** The CT-JUDGE-14 adversarial fixture set shall run through the decision path, answered by recorded `decide` fixtures. Each case must show that (a) the verdict is still a declared band; (b) a forged citation cannot enter, because the only citable spans are extractor spans verified by FR-JUDGE-30; and (c) confidence cannot reach auto-accept on a single decision-engine verdict. (c) already holds structurally: the single-judge base is at most 0.75 < 0.80 (`agg.py:590`), and a decision seat is always a single base judge. | FR-JUDGE-17; R73; ADR-13 | 1 |

**Non-functional requirements (new)**

| ID | Category | Requirement |
|---|---|---|
| NFR-JUDGE-06 | Performance (time behaviour) | On an accepted decision-seat unit, `dispatch` wall time p95 ≤ 1,000 ms on `cloud-hosted` and ≤ 3,000 ms on `edge-local` reference hardware (`unified-large`), at the default 16 citation questions. Assumption: extrapolated from the vendor's 70–500 ms and OpenJev's ~80–210 ms per question, pending PERF measurement. |
| NFR-JUDGE-07 | Performance (resource utilization) | Base-sweep wall time on the `F-JEV-PERF` corpus shall be ≤ 50% of the LLM-only base sweep when the measured fallback rate is ≤ 40%. Assumption: the target the user's "much faster" implies. It is a measured hypothesis like NFR-SYS-05, not a guarantee. |
| NFR-JUDGE-08 | Functional correctness | For a fixed `DecisionRequest` and recorded `Decision`, `decision_request`, `decision_eligibility`, `gate_decision` and the FR-JUDGE-28 construction are pure and deterministic. The same inputs yield the byte-identical `ScoringResult`. |
| NFR-JUDGE-09 | Fairness | Every submission in a `(question, criterion)` batch is pre-screened against a byte-identical `state` prefix and identical question text (NFR-JUDGE-02 extended). The acceptance test compares assembled `DecisionRequest`s across a batch. |

**Interfaces**

```python
# aeh/judge.py (additions)
DECISION_ENGINE_INVENTORY = "decision_engine_inventory"
JUDGE_DECISION_TEMPLATE_V = "judge-decision/1"     # pinned; changes with any render/instruction change

def is_decision_seat(unit: WorkUnit, run_config: RunConfig) -> bool: ...
def decision_fields(request: ScoringRequest) -> str: ...                              # pure
def decision_request(request: ScoringRequest, engine: DecisionEngine) -> DecisionRequest: ...   # pure
def decision_eligibility(request, engine, capabilities) -> Eligible | Ineligible: ...  # pure
def gate_decision(decision: Decision, request: ScoringRequest, engine) -> Accepted | BelowGate: ...  # pure
def decision_engine_metrics(handle, run_id: str) -> DecisionEngineMetrics: ...

class ScoringWorker:
    def __init__(self, store=None, provider=None, judge=None, *,
                 decision_provider: DecisionProvider | None = None,
                 run_config: RunConfig | None = None) -> None: ...   # engine + frozen panel read from it
    def dispatch(self, request: ScoringRequest, judge, *, unit: WorkUnit | None = None) -> ScoringResult: ...

@dataclass(frozen=True)
class ScoringResult:                 # existing fields, plus (appended, defaulted):
    scoring_engine: Literal["llm", "decision"] = "llm"
    engine_build: str | None = None
    prescreen_outcome: str | None = None      # None when no pre-screen applied
```

`JUDGE_DECISION_TEMPLATE_V` is recorded on the run's `provider_config.decision_engine` and hashed into `panel_build_ref` (FR-CONF-22). Changing the Jev render therefore changes work identity, as `JUDGE_PROMPT_TEMPLATE_V` does for the LLM render (CT-JUDGE-15).

**Data flow** (one score unit, decision seat, engine on):

```mermaid
sequenceDiagram
    participant X as M-PIPE executor
    participant J as ScoringWorker (M-JUDGE)
    participant S as Cohort store
    participant D as DecisionProvider (M-PROV)
    participant P as InferenceProvider (M-PROV)
    X->>J: assemble(unit) → ScoringRequest (pure, assert_isolated)
    X->>J: dispatch(request, judge, unit=unit)
    J->>S: read decision_prescreen[work_id]
    alt row exists
        J-->>J: reuse outcome (FR-JUDGE-33)
    else no row
        J-->>J: decision_eligibility(...)
        alt eligible
            J-->>J: decision_request(...) + numeral scan (FR-JUDGE-25)
            J->>D: decide(DecisionRequest, engine.model)
            D-->>J: Decision | Rejected | Malformed | (Unavailable/BuildChanged/RateLimited → propagate, FR-JUDGE-32)
            J-->>J: gate_decision(...) + citation verification
        end
        J->>S: INSERT OR IGNORE decision_prescreen (own tx)
    end
    alt accepted
        J-->>X: ScoringResult(scoring_engine="decision")
    else ineligible / below gate / rejected / malformed
        J->>P: complete(prompt_fields(request), judge, params)   (today's path, unchanged)
        P-->>J: Completion
        J-->>X: ScoringResult(scoring_engine="llm")
    end
    X->>J: persist(unit, result) → verdict (+ scoring_engine, engine_build) + mark_done, one tx
```

**Error handling.** This adds to the base table:
- `DecisionRequestError` at construction is a harness defect. It raises out of `dispatch` as `JudgmentError` with the cause and is a strike, because the unit cannot be judged by *either* path until the defect is fixed. It is not silently routed to the LLM.
- `IsolationViolation` from FR-JUDGE-25 is treated as today.
- The rest is covered by FR-JUDGE-31/32.

**Observability.** `decision_engine_metrics` (FR-JUDGE-36). CT-JUDGE-16's per-(criterion, judge) signals now carry a `scoring_engine` dimension through FR-STATS-25. Per call at DEBUG: work id prefix, outcome, gate, argmax band, latency. Never state bytes.

**Configuration (new).**
- Run-start (frozen, via `M-CONF`): `HARNESS_JEV_CONFIDENCE_THRESHOLD`, `HARNESS_JEV_CITE_THRESHOLD`, `HARNESS_JEV_MAX_CITATION_QUESTIONS`, `HARNESS_JEV_TOKEN_BYTES_RATIO`.
- Run-start (frozen): also `HARNESS_JEV_TOKEN_BYTES_RATIO` (3; the eligibility estimator's divisor, FR-CONF-21).
- Call-time: `HARNESS_JEV_FALLBACK_ALERT_RATE` (0.50), `HARNESS_JEV_ALERT_MIN_PRESCREENS` (50).

**Contract delta** (`CT-JUDGE`, v1.1 → **v2.0**, breaking: the write set and three clauses are amended)

Amended clauses (the amendment is stated. The IDs and the rest of each clause are unchanged):

| ID | Amendment |
|---|---|
| CT-JUDGE-05 | Add: "The field-order requirement applies to **LLM replies**. A decision-engine verdict is constructed by the module in canonical field order from typed answers. It has no reply to reorder, so the order mitigation (reason before band) is replaced there by the fact that the engine emits no free text at all." |
| CT-JUDGE-07 | Add: "The decision engine's calibrated confidence **selects the engine** for the decision seat (FR-JUDGE-27). It never selects a band, a route or an escalation. Once persisted, a decision-engine verdict's `self_confidence` is one weighted input to `M-AGG` exactly like an LLM's (weight 0.25 < escalation threshold 1.0, `agg.py:295`)." |
| CT-JUDGE-12 | Replace "Writes one `verdict` row per work unit and nothing else" with "Writes one `verdict` row per work unit, and for a decision-seat unit one `decision_prescreen` row, and nothing else." The prohibition list is unchanged. |
| CT-JUDGE-17 | Add: "A decision-engine answer is likely reproducible for an identical request and build (§1.2 inference), but this is **not promised** by this module either. Reproducibility is why FR-JUDGE-23 exists, not a property consumers may build on." |

New clauses:

| ID | Kind | Clause (assertable) | Consumers |
|---|---|---|---|
| CT-JUDGE-21 | behaviour | **Seat rule.** Per `(run, submission, criterion)`, at most one persisted verdict has `scoring_engine = 'decision'`, and it belongs to the unit whose judge is `RunConfig.panel[0].build_id`. A later rewrite of `panel_config` never creates a second seat. Escalation, random-arm and extension arms always have `scoring_engine = 'llm'`. | `M-AGG`, `M-STATS`, `M-ORCH` |
| CT-JUDGE-22 | behaviour | **Gate.** A decision-engine verdict exists iff `min(c_band, c_sufficient) > confidence_threshold` (strict), the band argmax is unique, and every cited span verified. Otherwise the unit's verdict comes from the LLM path, whose request is byte-identical to the request the unit would have produced with the engine off. | `M-AGG`, `M-CONFORM`, `M-STATS` |
| CT-JUDGE-23 | data | A decision-engine verdict's `band` is the declared band at the argmax of the Score probabilities, never a rounding of `score`. `band_ordinal` is its index. `cited_spans` ⊆ `request.evidence` (identical documents). `evidence_assessment` carries the `DECISION_ENGINE_INVENTORY` flag and is not prose reasoning. | `M-AGG`, `M-REVIEW`, `M-STATS` |
| CT-JUDGE-24 | data | Every verdict row carries `scoring_engine ∈ {'llm','decision'}` and `engine_build`. A `NULL` `scoring_engine` means a pre-delta row and is read as `'llm'`. `verdicts_for` returns `scoring_engine` on each `StoredVerdict`. | `M-AGG`, `M-STATS`, `M-PIPE` |
| CT-JUDGE-25 | error | An engine outage (`RateLimitedError`, `ProviderUnavailableError`, `BuildChangedError`) propagates from `dispatch` exactly like an LLM outage (CT-JUDGE-19). It never becomes an LLM fallback, a strike or a persisted row. A below-gate, ineligible, rejected or malformed pre-screen always becomes an LLM fallback, never a quarantine on that account alone. | `M-ORCH`, `M-PIPE` |
| CT-JUDGE-26 | behaviour | One engine sample per unit. The pre-screen row is written before the verdict. A redelivered unit reuses it and never calls `decide` a second time (FR-JUDGE-33/34). | `M-ORCH`, `M-PIPE` |
| CT-JUDGE-27 | security | The `DecisionRequest` is derived from the whitelisted `ScoringRequest` only. It passes `assert_isolated` and the FR-JUDGE-03 numeral scan over every question string, so the rubric surface stays numeral-free. Student bytes appear only inside the fenced `submission` field of `state`, never in a question string. | `M-CONFORM`, `M-AGG` |
| CT-JUDGE-28 | observe | `decision_engine_metrics` names are contract: `decision_prescreens`, `decision_accepted`, `decision_below_gate`, `decision_ineligible` (+ `reason`), `decision_rejected`, `decision_malformed`, `decision_accepted_rate`, `decision_fallback_rate`, `decision_latency_p50_ms`, `decision_latency_p95_ms`, alerts `decision_fallback_rate_high`, `decision_requests_rejected`. | `M-PIPE`, `M-STATS`, ops |
| CT-JUDGE-30 | security | A decision-engine `evidence_assessment` (the FR-JUDGE-29 inventory, which carries band probabilities as numerals) is never rendered into any model prompt: extraction, judging, escalation arms, synthesis, setup or ingestion. The only readers of `verdict.evidence_assessment` are statistics and display paths. | `M-SYNTH`, `M-STATS`, `M-CONFORM` |
| CT-JUDGE-29 | perf | NFR-JUDGE-06's latency bounds hold at the stated load. A decision-seat fallback costs at most one `decide` call plus today's LLM call. It is never more than one of each per unit. | `M-ORCH` |

*Requires (delta)*

| Depends on | Clauses relied on | What this module assumes |
|---|---|---|
| `M-PROV` | CT-PROV-17, -18, -19, -20, -21, -23 | Typed, validated answers with normalized confidence. Clear retryability. No engine substitution. A hermetic fixture double |
| `M-CONF` | CT-CONF-17, CT-CONF-18 | A frozen, resolved engine and thresholds for the whole run |
| `M-PKG` | CT-PKG-04 | Band order is ordinal ascending with 2–6 bands, so the Score levels are well-formed and index = ordinal |
| `M-ORCH` | CT-ORCH-04, CT-ORCH-29 | At-least-once delivery (FR-JUDGE-33 makes it safe). Every score unit names its judge by the panel member's build id, so the seat is computable against `RunConfig.panel[0]` |

*Compatibility.* **Breaking (v2.0).** Consumers to re-verify: `M-INTEG`, `M-AGG` (base §4.7), plus `M-PIPE`, `M-STATS`. The safety properties CT-JUDGE-02/03 are **not changed**: FR-JUDGE-25 extends their enforcement to the new request type. ADR-20 records the argument, as base §4.7 requires for changes near a safety property.

---

### 3.4 Module: `M-ORCH` — delta · identity, cost, counters

| ID | Requirement | Traces to | Phase |
|---|---|---|---|
| FR-ORCH-36 | `panel_config_json(panel, *, decision_engine=None)` shall add a key `"decision_engine": {"build": …, "provider": …, "threshold": "0.80", "cite_threshold": "0.50", "max_citation_questions": 16, "token_bytes_ratio": 3, "template": "judge-decision/1"}` **only when** an engine is present. Without an engine, the string is byte-identical to today. `panel_config` is already a `work_id` input (FR-ORCH-01), so turning the engine on, changing its build or changing its threshold yields new work ids and never mixes engines under one id. | FR-ORCH-01; CT-CONF-14 | 1 |
| FR-ORCH-37 | The `CallPlan` and cost estimate at run start (FR-PROV-09 / ceiling check) shall add one decision call per decision seat, costed by `DecisionCapabilities.cost_per_input_token × estimated tokens`, **on top of** the unchanged LLM estimate for every arm. The estimate assumes a 100% fallback rate, so the ceiling is never optimistic. | R5; FR-PROV-09 | 1 |
| FR-ORCH-38 | The `run_metrics` flush that persists `M-PROV` counters (CT-PROV-11) shall also persist the CT-PROV-24 decision counters under their names. | Seam 4 | 1 |
| FR-ORCH-39 | Base score units shall keep naming their judge by the panel member's `build_id` (today's behaviour, `panel_config_json`). Escalation, random-arm and extension additions shall never carry `RunConfig.panel[0].build_id` for a cell that already has it (today's `_extension_arms` rule). No ledger change is needed: `M-JUDGE` computes the seat from the unit's judge and the frozen `RunConfig` (CT-ORCH-29). | FR-JUDGE-23 | 1 |
| FR-ORCH-40 | The run row's `provider_config` snapshot (`orch.py:2978-2995`) shall add a `decision_engine` object (provider, build, the four frozen values, template version) **only when** an engine is present. `_verify_retention_at_start` (`orch.py:2971`) shall include the decision model in the retention set for `cloud-hosted`. An engine-off run's `provider_config` stays byte-identical. | FR-CONF-17 rehydration; FR-PROV-28; NFR-SYS-14 | 1 |

**Contract delta** (`CT-ORCH` → **v1.2**, additive)

| ID | Kind | Clause | Consumers |
|---|---|---|---|
| CT-ORCH-29 | data | Every score unit's `judge` is a panel member's `build_id` or an `escalation-arm-<k>` identity. No cell ever holds two units naming the same judge, and an escalation or random-arm addition never names an arm the cell already carries. | `M-JUDGE` |
| CT-ORCH-30 | behaviour | `panel_config` and `provider_config` for a run without a decision engine are byte-identical to their pre-delta serializations, so existing work ids, fixtures, audit records and resumes are unaffected. | `M-PIPE`, test suites |

*Requires (delta)*

| Depends on | Clauses relied on | What this module assumes |
|---|---|---|
| `M-PROV` | CT-PROV-24 | Decision counters exist under their names and are already included in `actual_cost`, so the ceiling check reads one figure |
| `M-CONF` | CT-CONF-20 | Engine-off `panel_build_ref` is the pre-delta value, so existing work identity is unchanged |

CT-ORCH-27 (exactly five alert names) is **not** amended. Decision-engine alerts live in `decision_engine_metrics` (CT-JUDGE-28), so no alert-name contract breaks.

---

### 3.5 Module: `M-AGG` — delta · engine-blind arithmetic, one guard

| ID | Requirement | Traces to | Phase |
|---|---|---|---|
| FR-AGG-18 | `aggregate` shall raise `PanelCorrelationError` when its input verdicts contain more than one verdict with `scoring_engine = 'decision'`. The composition layer treats the raise as a fault. It is unreachable while CT-JUDGE-21 holds, and exists so that a future change breaking the seat rule fails loudly instead of manufacturing unanimity. | ADR-21; FR-AGG-04 | 1 |
| FR-AGG-19 | Apart from FR-AGG-18, `aggregate`, `should_escalate` and the confidence computation shall not read `scoring_engine`. A decision-engine verdict is a verdict: same median, same α, same caps, same uncited multiplier, same self-confidence weight. | User directive: bias protection unchanged | 1 |

**Why the engine needs no confidence adjustment here** (worked from `agg.py`):
- A decision seat is a single base judge. Its base is `_band_position_prior`, 0.50–0.75, below the atomic auto-accept 0.80. So **a Jev verdict alone never auto-accepts**, exactly like an LLM verdict alone.
- An **uncited** verdict fires the uncited escalation signal at full weight (1.0 = threshold). FR-JUDGE-28's per-span citation Nouls are therefore what keep a confident Jev verdict from escalating by default. Without them every Jev cell would escalate and the speedup would vanish, which is why ADR-23 exists.

**Contract delta** (`CT-AGG` → **v2.1**, additive)

| ID | Kind | Clause | Consumers |
|---|---|---|---|
| CT-AGG-22 | error | `aggregate` refuses (`PanelCorrelationError`, not retryable, no write) a verdict set with two or more `scoring_engine = 'decision'` verdicts. | `M-PIPE` |
| CT-AGG-23 | behaviour | Aggregation, confidence and escalation are engine-blind (FR-AGG-19). Swapping `scoring_engine` on otherwise identical verdicts changes no output field. | `M-GRADE`, `M-REVIEW`, `M-STATS` |

*Requires (delta)*

| Depends on | Clauses relied on | What this module assumes |
|---|---|---|
| `M-JUDGE` | CT-JUDGE-21, CT-JUDGE-24 | At most one decision verdict per cell, and every verdict names its engine (NULL read as `llm`), so FR-AGG-18's guard can be evaluated from the verdicts alone |

CT-AGG-05 (safety property: the inversion) is unchanged.

---

### 3.6 Module: `M-GRADE` — delta · engine-blindness, written down

`M-GRADE` makes no model call (§1.1), so nothing in it is "powered" by any engine. The only delta is a guarantee that stays true:

| ID | Requirement | Traces to | Phase |
|---|---|---|---|
| FR-GRADE-19 | Grade computation, finalization, amendment and class rollup shall read no `verdict.scoring_engine`, no `decision_prescreen` row and no decision-engine configuration. Two runs whose `criterion_score` rows are identical produce identical `submission_grade` rows, whatever engines produced the verdicts. | User directive; CT-GRADE-07 | 1 |

| ID | Kind | Clause | Consumers |
|---|---|---|---|
| CT-GRADE-21 | behaviour | Grades are a function of `criterion_score` rows and the package's grade policy only. The engine that produced the underlying verdicts is not an input (FR-GRADE-19). | `M-REVIEW`, `M-STATS`, `M-CONSOLE` |

*Requires (delta)*

| Depends on | Clauses relied on | What this module assumes |
|---|---|---|
| `M-AGG` | CT-AGG-23 | Score rows are engine-blind, so a grade computed from them needs no engine input |

`CT-GRADE` → v1.2, additive: it writes down a behaviour that is already true.

---

### 3.7 Module: `M-STATS` — delta · measure the engine, don't trust it

"Better grading" is a claim to **measure**, not assume. The existing blind-label machinery is the instrument. Only its partitions are new.

| ID | Requirement | Traces to | Phase |
|---|---|---|---|
| FR-STATS-25 | `judge_signals` (FR-STATS-20) shall partition every per-(criterion, judge) signal by `scoring_engine`: uncited rate, insufficiency rate, band histogram, contract-violation rate and latency. It shall also report the decision-engine prescreen outcome mix from `decision_engine_metrics`. | CT-JUDGE-16; seam 4 | 1 |
| FR-STATS-26 | The chance-corrected agreement computed from blind judged labels (CT-STATS-01 admissibility unchanged) shall additionally be reported **per `scoring_engine` of the base verdict**. It covers decision-engine-accepted cells and LLM cells, and within the LLM cells it separates fallback-after-pre-screen from engine-off. The report never mixes an inadmissible label into any partition. | R-validation; CT-STATS-01 | 2 |
| FR-STATS-27 | `decision_gate_calibration(handle, package_version_id) -> GateCalibrationReport` shall bin accepted decision-engine verdicts by `band_confidence` (bins of 0.05 above the threshold). Per bin it reports exact-band agreement and adjacent-band agreement against blind labels, with a Wilson 95% interval and the label count. A bin with fewer than 20 labels reports `insufficient_data`, never a number (CT-STATS-03). | CT-STATS-03 | 2 |

| ID | Category | Requirement |
|---|---|---|
| NFR-STATS-06 | Functional suitability | **Engine non-inferiority gate** (Assumption: margin δ = 0.05 on ordinal α). A package version may rely on decision-engine verdicts in production only while FR-STATS-26's decision-engine α is ≥ the LLM base-verdict α − δ, over at least 60 blind labels per partition. Otherwise `validation_record` records `decision_engine_noninferior = false` and the operator console shows it. Below the 60-label minimum in either partition it records `insufficient_data`, never `true` or `false` (CT-STATS-03). The system never switches engines by itself: CT-CONF-14 forbids that mid-run, and turning the engine off is an operator decision for the next run. |

| ID | Kind | Clause | Consumers |
|---|---|---|---|
| CT-STATS-24 | data | Every agreement figure and signal is available per `scoring_engine`. A partition below its minimum label count reports `insufficient_data`, not a number. | `M-CONSOLE`, `M-CONFORM`, ops |

*Requires (delta)*

| Depends on | Clauses relied on | What this module assumes |
|---|---|---|
| `M-JUDGE` | CT-JUDGE-24, CT-JUDGE-28 | Every verdict row names its engine, and the prescreen outcome mix is read from `decision_engine_metrics` by its contract names |
| `M-CONF` | CT-CONF-20 | `panel_build_ref` distinguishes engine-on runs, so validation records are scoped per engine configuration |

`CT-STATS` → v1.2, additive. Where NFR-STATS-06's flag lives (a `validation_record` column vs the existing JSON payload) is decided with the implementation; §7 Q-J6 has the default.

---

### 3.8 Module: `M-PIPE` — delta · wiring and the trace

| ID | Requirement | Traces to | Phase |
|---|---|---|---|
| FR-PIPE-11 | `run_to_completion(store, run_id, *, provider, run_config, decision_provider=None)` shall construct the decision provider with `decision_provider_for(run_config.decision_engine.model)` when `decision_engine` is non-null and none was injected. It passes the provider and the run config (engine and frozen panel) to every `ScoringWorker` it builds (`pipeline.py:314`). With `decision_engine = None` no decision provider is built. | Seam 1 & 2 | 1 |
| FR-PIPE-12 | At run start, before the first dispatch, `run_to_completion` shall call the decision provider's `verify_retention` (cloud) and, for `OpenJevLocalProvider`, its build probe (FR-PROV-24). A failure refuses the run with the provider's error, and nothing is dispatched. | FR-PROV-24/28 | 1 |
| FR-PIPE-13 | `RunResult.stages["score"]` shall carry the `decision_engine_metrics` summary: counts by outcome, accepted and fallback rates, and the two alert flags. A run with the engine on never reports a bare `status=success` without it (seam 4). | Seam 4; CT-JUDGE-28 | 1 |
| FR-PIPE-14 | **When a decision engine is configured**, the executor's per-unit trace line for a score unit shall name the engine that produced the verdict: `…/crit by <judge>: <band> [decision]`, `[llm; prescreen=<outcome>]` for a seat that fell back, or `[llm]` for a non-seat. With `decision_engine = None`, the line is byte-identical to today's (no suffix), per NFR-SYS-14. | Seam 4; NFR-SYS-14 | 1 |

| ID | Kind | Clause | Consumers |
|---|---|---|---|
| CT-PIPE-08 | observe | With a decision engine configured, `RunResult.stages["score"]` includes the CT-JUDGE-28 summary by name. | `M-CONSOLE`, operator |
| CT-PIPE-09 | behaviour | A run whose `decision_engine` is null constructs no decision provider and performs no `decide` call. Its trace, verdicts and scores are identical to the pre-delta pipeline. | test suites |

*Requires (delta)*

| Depends on | Clauses relied on | What this module assumes |
|---|---|---|
| `M-PROV` | CT-PROV-22, CT-PROV-25 | `decision_provider_for` selects the provider lane by `ModelRef.provider`, and the retention gate covers the decision model before any dispatch |
| `M-JUDGE` | CT-JUDGE-25, CT-JUDGE-28 | An engine outage propagates out of `dispatch` (so the dispatch pass pauses), and the metrics summary has stable names |

`CT-PIPE` → v1.1, additive.

---

### 3.9 Module: `M-CONFORM` — delta · the two Jev backends

| ID | Requirement | Traces to | Phase |
|---|---|---|---|
| FR-CONFORM-10 | The conformance suite shall run a frozen fixture set, `F-JEV`, through the decision path on each configured decision backend (`openrouter-jev`, `openjev`). `F-JEV` has at least 40 cells covering every band position of a 4-band and a 6-band criterion, sufficient/insufficient evidence, 0/1/many spans and the FR-JUDGE-37 adversarial cases. The suite reports per backend: accepted rate, band-agreement between backends on cells both accepted (exact and adjacent), gate-confidence distribution, and ineligibility reasons. It writes a backend-scoped validation record. | NFR-PROV-06; R30 | 1 |
| FR-CONFORM-11 | The suite shall report, per backend, the share of `F-JEV` cells where the decision-engine band differs from the recorded LLM-panel median band. This is a quality diagnostic, **not** a pass/fail gate until Q-J5 sets one. | NFR-STATS-06 | 1 |

| ID | Kind | Clause | Consumers |
|---|---|---|---|
| CT-CONFORM-15 | observe | Per decision backend, the conformance report names `decision_accepted_rate`, `decision_band_exact_agreement`, `decision_band_adjacent_agreement` and `decision_llm_median_divergence`. | CI and release gating |

*Requires (delta)*

| Depends on | Clauses relied on | What this module assumes |
|---|---|---|
| `M-PROV` | CT-PROV-23 | The E1 arm replays decisions hermetically from the fixture double and fails loudly on a miss |

`CT-CONFORM` → v1.1, additive.

---

### 3.10 Module: `M-STORE` — delta · migrations and the pin

| Version | Tier | Owner | Name | Statements |
|---|---|---|---|---|
| 28 | Cohort | `aeh.judge` | `judge_decision_prescreen` | `CREATE TABLE decision_prescreen (…)` per FR-JUDGE-34, `work_id TEXT PRIMARY KEY`, `outcome` CHECK over the five values, `CREATE INDEX idx_prescreen_run ON decision_prescreen (run_id, criterion_id)` |
| 29 | Cohort | `aeh.judge` | `judge_verdict_engine` | `ALTER TABLE verdict ADD COLUMN scoring_engine TEXT CHECK (scoring_engine IN ('llm','decision'))`; `ALTER TABLE verdict ADD COLUMN engine_build TEXT` |

These go in the same landing:
- `COMPLETE_SCHEMA_VERSIONS[Tier.COHORT]` 27 → 29.
- The `CLAUDE.md` migration-chain paragraph gains "`aeh.judge` owns Cohort's last migration (`judge_verdict_engine`, 29) and the one before it (`judge_decision_prescreen`, 28)".
- New statements join `JUDGE_STATEMENTS`, and new execute sites join `KNOWN_EXECUTE_SITES`. The SEC-15 census line numbers move.

Both migrations are additive. Pre-existing verdict rows read `scoring_engine = NULL` → `'llm'` (CT-JUDGE-24).

### 3.11 Module: `M-PROV` + `M-CONF` — delta (1.7) · OpenJevSmall, the small-machine decision provider

#### 3.11.1 Does it solve the co-residency problem? The check, and the verdict

The problem (FR-CONF-23, design Q-J4, test-plan Q-37) has three parts:
- The reference edge machine, `unified-small`, is 32 GB of Apple unified memory with a 30B-class MoE judge (HLD §8.1). That judge is ~18 GB at 4-bit, before its KV cache.
- OpenJev's smallest build (MLX 4-bit) is ~15 GB.
- 18 + 15 GB plus two KV caches and the OS does not fit, and HLD §8.1 declares the profile "one model resident at a time".

| Question | Evidence | Answer |
|---|---|---|
| Does it fit in memory? | 4B v5 weights are 9.08 GB bf16. 18 + 9 ≈ 27 GB of weights on a 32 GB machine whose default GPU wired-memory limit is below the physical 32 GB. The 2B v5 is roughly half. | **Plausibly, but tight** for 4B bf16 once both KV caches are counted. It is comfortable for 2B. HLD §8.5 says memory headroom is "an empirical property ... not derivable from the architecture", so the arithmetic is not proof. |
| Does it run at usable speed on the reference hardware? | No MLX build. The only serving paths are transformers and SGLang (CUDA), tested on an RTX A6000. The model has hybrid linear-attention layers whose fast kernels are CUDA-oriented. Each decision costs one forward pass **per option per question**: `L` band levels + 2 for sufficiency + 2 per cited span. That is about 40 passes at 16 spans, with no prefix cache off CUDA. | **Unknown.** This is the decisive constraint, and nothing published answers it for Apple silicon. |
| Does it speak the decision protocol? | Typed Choice/Score/Noul in, probabilities out, but only through a Python API. No confidence field. `score` is treated as unordered options. Long states are windowed. | **With a shim.** The windowing must be refused, because it changes answer semantics and drops the criterion prefix from later windows. |
| Is its answer as trustworthy as Jev's? | JevBench 0.814–0.866 vs Jev 1.13's 0.87 on the same public items. Hard tier 0.622. Probabilities are normalised entailment, not RLCD-calibrated confidence. Injection drops accuracy to 0.467/0.436. | **Not established.** The 0.80 gate means something different on this engine, and the injection weakness is material for student submissions (R73). |
| Licence | MIT | **Yes.** It resolves Q-J10 for this engine only. |

**Verdict: plausible, not proven.** OpenJevSmall solves the *memory* half of the problem on paper. It does not yet solve it in practice. Whether it runs fast enough beside the judge on a 32 GB Apple machine is unmeasured, and the design cannot derive it. The design therefore adds OpenJevSmall as a **separate, opt-in provider behind a measured gate**:
- it is admitted on `unified-small` only as an `Assumption:` that NFR-SYS-16's manual acceptance run on the reference machine confirms or retracts;
- it is never selected automatically because a machine is small;
- its injection robustness is measured live before it is recommended (FR-CONFORM-12).

No provider code is written by this delta. The base `DecisionProvider` surface does not exist yet, and code arrives through `/fix-issue` from the issues `/plan-to-issues` creates.

#### 3.11.2 Architecture

```
harness process (aeh, no torch)                         separate process (loopback only)
┌──────────────────────────────┐   POST /v1/systemone   ┌───────────────────────────────────────┐
│ OpenJevSmallLocalProvider    │ ─────────────────────▶ │ tools/openjev_small_shim              │
│  (M-PROV, stdlib HTTP)       │ ◀───────────────────── │  vendor openjev_decide.py (pinned rev) │
│                              │   GET  /v1/build       │  transformers + torch, bf16 weights    │
└──────────────────────────────┘                        └───────────────────────────────────────┘
```

The shim is a **companion artifact owned by `M-PROV`**, kept outside `src/aeh` and outside the harness import graph. It keeps torch out of the harness process (CT-PROV-15, FR-PROV-03, CT-PROV-28). It speaks exactly the §1.2 request/response schema, so `OpenJevSmallLocalProvider` reuses FR-PROV-20's validation and FR-PROV-19's confidence normalisation unchanged.

#### 3.11.3 Functional requirements (new)

| ID | Requirement | Traces to | Phase |
|---|---|---|---|
| FR-PROV-30 | `OpenJevSmallLocalProvider` shall be a **separate class** from `OpenJevLocalProvider`, selected by `ModelRef.provider == "openjev-small"`. It POSTs `{model: $HARNESS_OPENJEV_SMALL_MODEL_NAME (default "openjev-small"), state, questions}` to `<HARNESS_OPENJEV_SMALL_BASE_URL>/v1/systemone` (default `http://127.0.0.1:3001`). It applies FR-PROV-22's loopback rule, with its own `HARNESS_OPENJEV_SMALL_ALLOW_REMOTE` (default false), FR-PROV-23's error table, and FR-PROV-20's validation. | User request | 1 |
| FR-PROV-31 | **Build identity.** At run start (`verify_build`) and every `HARNESS_OPENJEV_SMALL_BUILD_PROBE_EVERY` calls (default 500), the provider shall `GET <base>/v1/build`. It compares `weights_sha256` with the `ModelRef`'s `@sha256:` digest and `subfolder` with the build path's final segment, and raises `BuildChangedError` on any mismatch. Every `Decision.resolved_build` is `openjev-small:<subfolder>@sha256:<digest>`. Unlike OpenJev (Q-26), the digest is verified, because the shim computes it (FR-PROV-36). | FR-PROV-04/05 | 1 |
| FR-PROV-32 | `DecisionCapabilities` for `openjev-small`: `max_context_tokens = HARNESS_OPENJEV_SMALL_MAX_STATE_TOKENS` (default 6,000; Assumption: one ~8k-token encoder window minus the hypothesis and template budget), `max_choice_options = 16`, `max_questions = 64` (Assumption: each option is a forward pass, so large option sets cost linearly), `cost_per_input_token = None`, `deterministic = True`. FR-JUDGE-26 therefore routes oversize units to the LLM **before** any request is sent. | FR-PROV-27; FR-JUDGE-26 | 1 |
| FR-PROV-33 | **Shim placement.** The shim shall live at `tools/openjev_small_shim/` with its own `requirements.txt` (torch, transformers ≥ 5.17, pinned). It vendors `openjev_decide.py` and `modeling_openjev.py` at a pinned Hugging Face revision recorded in the shim's `VENDOR.md`. No module under `src/aeh` imports it, and it imports nothing from `aeh`. `requirements-dev.txt` and `pyproject.toml` do not gain torch. | CT-PROV-15; FR-PROV-03 | 1 |
| FR-PROV-34 | **Shim translation.** The shim's `translate(request) -> vendor_questions` and `answer(vendor_result, request) -> response` shall be pure functions, testable without torch through an injected scorer: <br>• **Noul:** options `["no","yes"]`; `criteria.false`/`true` become their rubric texts via the vendor `RUBRIC_MARK` convention; the answer is `{type:"noul", noul: p_yes}`. <br>• **Choice:** options are the criteria keys, with descriptions as rubric texts; the answer is `{type:"choice", choice: <argmax, first in declared order on a tie>, probabilities}`. <br>• **Score:** options are the level strings in order, labelled by index; the answer is `{type:"score", score: Σ i·p_i, legend: {"i": level_i}, probabilities: {"i": p_i}}`. <br>No answer carries `confidence`, so the provider always derives it (FR-PROV-19, CT-PROV-27). | §1.2 schema; FR-PROV-19/20 | 1 |
| FR-PROV-35 | **No windowing.** The shim shall refuse with HTTP 422 (`{"error": "state_exceeds_window"}`) any request whose state, together with the longest hypothesis it would build, exceeds one encoder window. It shall never call the vendor windowing path, and shall set the vendor `window_chars` to a value that disables it. The shim also refuses with 422 a Choice with more than 16 options and a request with more than 64 questions. The provider maps 422 to `DecisionRequestRejectedError` (FR-PROV-23), so the unit falls back to the LLM (FR-JUDGE-31) and the `decision_requests_rejected` alert fires (FR-JUDGE-36): a window refusal means FR-PROV-32's estimate was too optimistic. | Vendor semantics (§1.2); FR-JUDGE-26 | 1 |
| FR-PROV-36 | `GET /v1/build` shall return `{repo, subfolder, revision, weights_sha256, dtype, device}`. `weights_sha256` is computed from the loaded `model.safetensors` bytes at shim start. `device` is the torch device the model runs on (`cpu`, `mps`, `cuda:N`). | FR-PROV-31; FR-CONF-28 | 1 |
| FR-PROV-37 | `decision_provider_for` (FR-PROV-26) shall map `openjev-small` to `OpenJevSmallLocalProvider`. The provider name `openjev-small` is accepted only for `edge-local` (FR-CONF-27) or `fixture`. | FR-PROV-26 | 1 |
| FR-CONF-27 | **Opt-in binding.** `edge-local` shall accept `decision_engine.model.provider ∈ {openjev, openjev-small}` (amends FR-CONF-19's `edge-local` row). `openjev-small` is selected **only** by the operator's `HARNESS_JEV_BUILD`/provider configuration. Nothing in resolution, residency checking or error handling substitutes it for `openjev` because the hardware is small. The residency refusal *names* it as an alternative; it never *chooses* it. The ModelRef build is a weights path plus quantization plus digest (FR-CONF-20), e.g. `/models/openjev-small/qwen3.5-4b-nli-v5@sha256:<hex>`, quantization `bf16`. The 4B, 2B, nvfp4 and any self-quantized build are **distinct builds**, each with its own `panel_build_ref` and so its own validation record (HLD §8.1: "a package validated against one quantization is not automatically valid against another"). **Build choice (1.7.1, user decision):** `qwen3.5-4b-nli-v5` is the recommended build, and `qwen3.5-2b-nli-v5` is the **fallback build** for machines where 4B fails NFR-SYS-16. The operator makes the fallback at configuration time by naming the 2B build. It is never a runtime switch: a run whose served build changes raises `BuildChangedError` (FR-PROV-31), and nothing swaps 2B in when 4B is slow, missing or out of memory. The reference config's comments name both builds. | User request; CT-CONF-14 | 1 |
| FR-CONF-28 | **Per-engine residency** (supersedes FR-CONF-23's boolean). `HardwarePolicy.decision_coresident: Mapping[str, str]` maps each admitted decision provider to its placement, `"shared"` (co-resident with the judge in the same memory pool) or `"cpu"` (must run on CPU so the judge keeps the accelerator). Values (Assumption, pending NFR-SYS-16): <br>• `unified-large`: `{openjev: shared, openjev-small: shared}`; <br>• `unified-small`: `{openjev-small: shared}`; <br>• `discrete-gpu`: `{openjev-small: cpu}`. HLD §8.1's "exactly one model in VRAM" is kept by putting the decision model in system RAM. <br>A provider absent from the map is refused (FR-CONF-23's message). For placement `cpu`, run start (FR-PIPE-12) reads `/v1/build.device` and refuses the run unless it is `cpu`. This amends HLD §8.1's `unified-small` "one model resident at a time" **for the decision model only**, and ADR-27 records it. | HLD §8.1; ADR-27 | 1 |
| FR-CONFORM-12 | **Live injection robustness.** On each configured decision backend (live on E2/E7/E4), the conformance suite shall run the F-ADV-INJ twin pairs through the decision path and the seat-0 LLM judge. It reports `decision_injection_flip_rate` (the share of pairs whose injected twin received a different band from its benign twin, moved in the direction the injection demanded) beside `llm_injection_flip_rate` for the same pairs. It writes `decision_engine_injection_robust = (decision rate ≤ llm rate + 0.05)` (Assumption: margin) to the backend-scoped validation record. The console shows "not recommended" for an engine build whose flag is false. Recorded `decide` fixtures (FR-JUDGE-37) cannot measure this, since they measure the harness, not the model. | R73; ADR-13; user request | 1 |

#### 3.11.4 Non-functional requirements (new)

| ID | Category | Requirement |
|---|---|---|
| NFR-PROV-09 | Security | The shim binds `127.0.0.1` by default, refuses a non-loopback bind unless started with `--allow-remote`, logs no request bodies, and makes no outbound network call after weights are loaded (`HF_HUB_OFFLINE=1` is set by its launcher). |
| NFR-JUDGE-10 | Performance (time behaviour) | On E4 (`unified-small`, the reference machine) with `openjev-small` (4B v5, bf16) co-resident with the reference judge, a decision-seat dispatch at the default 16 citation questions shall have p95 ≤ 20 s. Assumption: about 40 forward passes of up to ~6k tokens. This is a measured hypothesis, not a transfer of NFR-JUDGE-06. **The figure that matters is the ratio to the seat-0 LLM call on the same machine.** If `openjev-small` is not faster than the LLM it pre-screens, it adds cost without benefit, and operators should be told so rather than defaulted into it. |
| NFR-SYS-16 | Capacity (acceptance) | **Reference-hardware co-residency gate** (manual, E4, like PERF-10). `edge-local`/`unified-small` with `openjev-small` and the reference 30B-class judge at its quantization runs F-JEV-PERF at the profile's concurrency ceiling. Peak memory (both models' weights plus both KV caches plus the shim) stays under the profile ceiling measured per HLD §8.5, with no swap-induced failure and no out-of-memory error. NFR-JUDGE-10 holds in the same run. **Until this passes, FR-CONF-28's `unified-small` entry is an unconfirmed Assumption and release notes say so.** If it fails for 4B bf16, it is re-run for 2B v5, the designated fallback build (FR-CONF-27). |

#### 3.11.5 Contract delta

`CT-PROV` → **v1.2**, additive: a new provider, new clauses. `CT-CONF` → **v2.1**, additive: a new provider value handled by `M-PROV` in the same change, and residency data. `CT-CONFORM` → v1.2, additive.

| ID | Kind | Clause (assertable) | Consumers |
|---|---|---|---|
| CT-PROV-26 | behaviour | `OpenJevSmallLocalProvider` is a distinct class, selected only by `decision_provider_for` on `provider == "openjev-small"`. It sends nothing to a non-loopback host unless `HARNESS_OPENJEV_SMALL_ALLOW_REMOTE=true`. A state longer than one encoder window is **refused, never windowed**: no answer is ever the maximum over windows. | `M-CONF`, `M-JUDGE`, `M-CONFORM` |
| CT-PROV-27 | data | Every answer from `openjev-small` has `confidence_source = "derived"`. This engine never reports a confidence, and consumers must not read its confidence as the calibrated statistic Jev reports. | `M-JUDGE`, `M-STATS` |
| CT-PROV-28 | security | The shim is never imported by `aeh`, and `torch`/`transformers` never appear in the harness import graph or its declared dependencies. The only channel between them is loopback HTTP. | all modules |
| CT-CONF-21 | behaviour | `openjev-small` is never selected implicitly. A `RunConfig` has `provider == "openjev-small"` only if the operator's configuration named it. Residency is admitted per `(hardware_profile, decision provider)` and refused otherwise, with a message naming the admitted alternatives. | `M-PROV`, `M-JUDGE`, operator |
| CT-CONFORM-16 | observe | Per decision backend, the conformance report names `decision_injection_flip_rate`, `llm_injection_flip_rate` and `decision_engine_injection_robust`. | CI and release gating, `M-CONSOLE` |

*Requires (delta)*

| Depends on | Clauses relied on | What this module assumes |
|---|---|---|
| OpenJevSmall shim | (companion, FR-PROV-33…36) | §1.2 schema, 422 on window overflow, `/v1/build` with a verified digest and device |
| `M-CONFORM` ← `M-PROV` | CT-PROV-26, CT-PROV-27 | The live injection run drives the same provider class the harness uses, and reads derived confidence |

*Compatibility.* `CT-PROV-17…25` apply to `OpenJevSmallLocalProvider` unchanged. It joins CS-PROV-DECIDE, so the three live providers and the fixture double run one clause suite. `CT-PROV-22` is unchanged and does not cover this class; CT-PROV-26 does.

**Configuration (new).** `HARNESS_OPENJEV_SMALL_BASE_URL` (`http://127.0.0.1:3001`), `HARNESS_OPENJEV_SMALL_MODEL_NAME` (`openjev-small`), `HARNESS_OPENJEV_SMALL_ALLOW_REMOTE` (false), `HARNESS_OPENJEV_SMALL_MAX_STATE_TOKENS` (6000), `HARNESS_OPENJEV_SMALL_BUILD_PROBE_EVERY` (500), `HARNESS_OPENJEV_SMALL_TIMEOUT_S` (60). Shim-side: `OPENJEV_DEVICE`, `OPENJEV_DTYPE` (vendor knobs), `--port`, `--allow-remote`.

**Operator guidance** (goes in the reference config's comments):
- The engine is opt-in.
- Consider lowering `HARNESS_JEV_MAX_CITATION_QUESTIONS` on this engine, since each citation costs two forward passes.
- The threshold defaults to 0.85 for this engine (1.7.1). Lower it only with FR-STATS-27 calibration data behind the change.
- Use the 4B build. Configure the 2B build only if 4B fails NFR-SYS-16 on the machine.

---

## 4. System-level design (delta)

### 4.1 Dependency diagram (delta)

```mermaid
graph LR
  CONF[M-CONF] --> PROV[M-PROV]
  PROV -->|complete| JUDGE[M-JUDGE]
  PROV -->|decide: new| JUDGE
  CONF -->|decision_engine: new| JUDGE
  JUDGE --> AGG[M-AGG]
  AGG --> GRADE[M-GRADE]
  JUDGE -->|decision_prescreen, scoring_engine: new| STATS[M-STATS]
  PIPE[M-PIPE] -->|decision_provider_for: new| PROV
  PIPE --> JUDGE
  CONFORM[M-CONFORM] -->|decide| PROV
  PROV -->|HTTPS| OR[(OpenRouter Decisions API · Jev)]
  PROV -->|loopback HTTP| OJ[(OpenJev shim + vLLM)]
```

The only new edges are `M-PIPE`→`M-PROV.decision_provider_for` and `M-STATS`'s read of `decision_prescreen`. That table lives in the Cohort tier `M-STATS` already reads. There is no new module-level dependency and no cycle.

### 4.2 Key flow: a cell under Jev (base panel of 1, the fast configuration)

1. `M-ORCH` enumerates one extract unit and one score unit for `panel[0]` (unchanged).
2. Extraction and the pre-panel integrity gate run (unchanged).
3. The score unit is the decision seat. `M-JUDGE` pre-screens with Jev:
   - Gate > 0.80 → the Jev verdict is persisted with `scoring_engine='decision'`, `self_confidence = c_band` and cited spans.
   - Otherwise → the seat-0 LLM judge is called exactly as today → `scoring_engine='llm'`.
4. `M-AGG` aggregates the single verdict (engine-blind). The single-judge base is ≤ 0.75, so the cell is never auto-accepted alone. Routing and `should_escalate` run on observable signals as today.
5. On escalation, `M-ORCH` widens 1→3 with LLM arms exactly as today: panel members first, then derived `escalation-arm-<k>` refs (`pipeline.judge_for`). The widened panel is {Jev-or-LLM seat 0, LLM, LLM}. The added arms are as independent of each other as they are today, and the Jev seat adds no correlation among them. α and the caps apply as today.
6. `M-GRADE`, `M-REVIEW` and `M-SYNTH` run unchanged.

**Where the speedup comes from.** Step 3 on every cell. The base sweep is one unit per cell per base arm and dominates call volume. With a base panel of 3, only seat 0 is pre-screened, so the speedup is roughly one third of the base sweep. Q-J1 asks whether the operator wants the panel-of-1 base for Jev runs.

### 4.3 System-wide NFR (delta)

| ID | Requirement |
|---|---|
| NFR-SYS-14 | With `HARNESS_DECISION_ENGINE=off`, every artifact a run produces is byte-identical to the pre-delta system for the same inputs and fixtures: `work_id`s, `panel_config`, `provider_config`, `ProfileSummary`, prompts, verdicts, scores, grades and trace. There are two stated exceptions, both schema-level: verdict rows carry the new `scoring_engine = 'llm'` and `engine_build` columns, and the run's `RunConfig` has a 13th field whose value is `None`. This is the regression anchor for "everything else stays the same". |
| NFR-SYS-15 | `edge-local` with OpenJev makes no network call to a non-loopback host on the decision path, and `cloud-hosted` sends decision requests only to the configured OpenRouter endpoint. The existing egress census (CT-PROV-15) extends to both. |

### 4.4 Architecture Decision Records

#### ADR-20: The decision engine is an engine choice inside `M-JUDGE`, not a provider fallback and not a new stage
- **Context.** The brief wants Jev first and the LLM on low confidence. Base contracts CT-PROV-08 (no substitution), CT-PROV-06/CT-JUDGE-11 (one judgment, one sample) and CT-JUDGE-07 (self-confidence never routes alone) read, at first sight, as forbidding exactly that.
- **Decision.** The gate lives in `M-JUDGE` and chooses *which engine's answer is the verdict* for one unit. A below-gate Jev answer is a recorded **pre-screen**, never a verdict. Exactly one verdict is produced per unit, by one engine, once. `M-PROV` still never substitutes on failure (CT-PROV-21), and engine outages still pause (ADR-26). Jev's confidence never selects a band, route or escalation: `M-AGG` treats the persisted verdict exactly as any other. No new ledger stage is added, so orchestration is unchanged.
- **Consequences.** CT-JUDGE v2.0 (§3.3), with the amended clauses listed. CT-PROV only gains clauses. CT-JUDGE-02/03 (safety properties) are untouched in substance and enforced on the new request type.
- **Alternatives rejected.** (a) A new Sweep-2a "decision stage" enqueueing LLM units only for fallbacks. It is cleaner for edge residency, but it changes orchestration, the ledger and work identity, which the brief forbids. It is recorded as Q-J4's escape hatch. (b) A fallback inside `M-PROV`. It would hide engine choice from the verdict's provenance and violate CT-PROV-08 literally.

#### ADR-21: At most one decision-engine verdict per cell (the seat rule)
- **Context.** Jev's answers to identical input are at least highly correlated (§1.2 inference), and every arm of a cell sees the identical request. Running Jev on several arms manufactures unanimity: α ≈ 1 and false confidence.
- **Decision.** Only the unit judged by the frozen `RunConfig.panel[0]` is the decision seat (CT-JUDGE-21). `M-AGG` refuses a panel with two decision verdicts (CT-AGG-22).
- **Consequences.** Panel independence is exactly as today: no better, no worse. The speedup scales with the share of calls that are base seat-0 calls.
- **Alternative rejected.** Jev on every arm with perturbed inputs (e.g. level order shuffles). OpenJev reports a 2.3% answer change under shuffling. Using that as "independence" would be fake diversity dressed as a panel.

#### ADR-22: Bands via Score argmax, never via the continuous score
- **Decision.** Score over the declared bands. Band = argmax of per-level probabilities. `score` is kept for observability only.
- **Why.** FR-AGG-02 forbids ordinal averaging. `score` is a probability-weighted mean. An argmax tie cannot pass the gate for any threshold ≥ 0.5 (a two-way tie has confidence ≤ (n/2 − 1)/(n − 1) < 0.5) and is still refused explicitly.

#### ADR-23: Citations as one Noul per extracted span
- **Context.** Jev emits no text. An uncited verdict fires a full-weight escalation signal (`agg.py:295` family) and takes ×0.80 confidence, so uncited Jev verdicts would all escalate and erase the benefit.
- **Decision.** Ask one Noul per own-evidence span (labels `a`…`z`, instruction carries only the label). Cite spans with `p_true ≥ cite_threshold`. Cited spans are identical copies of extractor spans and are re-verified (FR-JUDGE-30).
- **Consequences.** The question count grows with span count, which is capped by `max_citation_questions`. Beyond the cap, the unit is ineligible rather than partially cited.

#### ADR-24: OpenRouter's Decisions API, with a configurable URL
- **Decision.** Default to `POST /api/alpha/decisions`. It is the endpoint whose reference documents `provider` preferences (needed for FR-PROV-11 pinning, `allow_fallbacks:false` and FR-PROV-14/28 zero retention) and `usage.cost`. `/api/v1/systemone` is the alternative for TypeSafe-SDK compatibility.
- **Risk.** The Decisions API is labelled *alpha*. `HARNESS_JEV_OPENROUTER_URL` lets an operator move to `/api/v1/systemone` without a code change. The request body is the same shape except `provider`, whose acceptance on that path is Q-J2.

#### ADR-25: The decision engine is frozen in `RunConfig` (13th field)
- **Decision.** Add `decision_engine` to `RunConfig` and to `panel_build_ref`/`panel_config`. Freeze the threshold and citation cutoff at run start.
- **Why.** CT-CONF-14 (safety property): a run's grader must not change underneath it, and the threshold decides which engine grades whom. The extractor-ref precedent (no home in `RunConfig`, `pipeline.py:39`) is not followed on purpose: the extractor does not decide scores, and the decision engine does.
- **Cost.** CT-CONF v2.0 (set equality 12 → 13).

#### ADR-26: An engine outage pauses the run; only confidence triggers fallback
- **Decision.** `ProviderUnavailableError`, `BuildChangedError` and exhausted `RateLimitedError` from Jev propagate and pause the run (FR-ORCH-30), exactly as for an LLM judge. Rejected (400/422) and malformed-after-retries outcomes fall back, because they are "Jev did not provide a confident result" for *this* unit, not an outage.
- **Why.** The brief's trigger is confidence. Falling back on outage would silently change the engine mix of a run mid-flight: part of a class graded by Jev and part by the LLM because of a network blip. The confidence gate does this by design and records it per unit. An outage would do it by accident. R1 and CT-PROV-08 point the same way.
- **Open.** Q-J7 asks whether the user wants an explicit, run-start-frozen `on_outage=llm` policy.

#### ADR-27: Per-engine residency, and OpenJevSmall as an opt-in engine behind a measured gate
- **Context.** OpenJev does not fit beside the judge on `unified-small`, and not in a 16–24 GB `discrete-gpu` card at all (HLD §8.1). The user proposed OpenJevSmall (4B NLI cross-encoder, 9.1 GB bf16).
- **Decision.** Residency becomes a per-provider map with a placement (FR-CONF-28). OpenJevSmall is added as a separate provider over a loopback shim (FR-PROV-30…36). It is **opt-in only** (CT-CONF-21) and admitted on `unified-small` as an Assumption until NFR-SYS-16 passes on E4. On `discrete-gpu` it is admitted only on CPU, which preserves HLD §8.1's one-model-in-VRAM rule.
- **Why not auto-select it on small machines.** That would make the grader a function of the machine: two schools with the same package would get different engines without anyone choosing it. CT-CONF-14 and R1 forbid a grader nobody chose.
- **Why a shim and not in-process.** The vendor ships Python over torch. Loading it in-process would put torch in the harness import graph and make `aeh` a GPU application (CT-PROV-15, CT-PROV-28).
- **Consequences.** The decision seat on small machines may be answered by a weaker, injection-prone, uncalibrated engine. The structural limits still hold: a single verdict never auto-accepts, escalation brings in LLMs, and the blind sample reaches the cell. FR-CONFORM-12 measures injection robustness per build, and NFR-STATS-06 measures agreement per build. HLD §8.1's `unified-small` residency sentence is amended for the decision model only.
- **Alternatives rejected.** (a) Self-quantizing OpenJev 27B to fit: an unvalidated build with a CC BY-NC licence. (b) The ADR-20 Sweep-2a sequential decision pass: it would solve residency for any engine size, but it changes orchestration, which the brief forbids. It stays the fallback if NFR-SYS-16 fails for every OpenJevSmall build.

### 4.5 Landing order (dependency-safe sequencing for `/plan-to-issues`)

1. **Provider surface:** FR-PROV-16…20, FR-PROV-25 (fixture `decide`), FR-PROV-26/27, FR-PROV-29. Depends on nothing new. Unblocks everything below with hermetic fixtures.
2. **Two live providers (parallel):** FR-PROV-21/23/24 (OpenRouter half) + FR-PROV-28 → `JevOpenRouterProvider`. FR-PROV-22/23/24 (OpenJev half) → `OpenJevLocalProvider`. Each depends on 1.
3. **Run configuration:** FR-CONF-17…26, FR-ORCH-36/39/40 (identity), `CT-CONF-C02` 12→13 in the same PR. Depends on 1 (for `ModelRef` role / provider names).
4. **Schema:** Cohort 28/29, pin bump, `CLAUDE.md` chain paragraph. It can land with 5 or just before it.
5. **Judge engine:** FR-JUDGE-22…35. Depends on 1, 3 and 4. Suggested split:
   - (a) pure mapping, eligibility and gate: FR-JUDGE-23/24/25/26/27/28/29.
   - (b) dispatch integration, fallback, outage, pre-screen reuse and persistence: FR-JUDGE-22/30/31/32/33/34/35.
6. **Guards and composition:** FR-AGG-18/19, FR-GRADE-19, FR-ORCH-37/38, FR-PIPE-11…14, FR-JUDGE-36. Depend on 5.
7. **Measurement:** FR-STATS-25 (Phase 1), FR-CONFORM-10/11, FR-JUDGE-37. Depend on 6.
8. **Phase 2:** FR-STATS-26/27, NFR-STATS-06, which need blind labels to accumulate.
9. **OpenJevSmall (1.7):** FR-PROV-30…37 and FR-CONF-27/28 after steps 1–3. The shim (FR-PROV-33…36) can land in parallel with the provider. FR-CONFORM-12 lands after step 7. NFR-SYS-16 and NFR-JUDGE-10 are manual E4 runs before the engine is documented as supported on `unified-small`.

The `type:story` / `type:test` pairing (`CLAUDE.md` co-evolution) applies to every step. Every test story for steps 2–7 lands red under `@pytest.mark.writtenahead` with a `WRITTEN_AHEAD_BLOCKERS` entry.

### 4.6 Contract register (delta)

| Module | Contract | Version | Stability | New clauses | Amended | Consumed by (added) |
|---|---|---|---|---|---|---|
| `M-PROV` | CT-PROV | 1.2 (additive) | stable | 12 (17–28) | — | — |
| `M-CONF` | CT-CONF | **2.0 (breaking)**, then 2.1 (additive, 1.7) | stable | 5 (17–21) | CT-CONF-02 | `M-PIPE` |
| `M-JUDGE` | CT-JUDGE | **2.0 (breaking)** | stable | 10 (21–30) | CT-JUDGE-05, -07, -12, -17 | `M-STATS`, `M-PIPE` |
| `M-ORCH` | CT-ORCH | 1.2 (additive) | stable | 2 (29–30) | — | — |
| `M-AGG` | CT-AGG | 2.1 (additive) | stable | 2 (22–23) | — | — |
| `M-GRADE` | CT-GRADE | 1.2 (additive) | stable | 1 (21) | — | — |
| `M-STATS` | CT-STATS | 1.2 (additive) | stable | 1 (24) | — | — |
| `M-PIPE` | CT-PIPE | 1.1 (additive) | provisional | 2 (08–09) | — | — |
| `M-CONFORM` | CT-CONFORM | 1.2 (additive) | stable | 2 (15–16) | — | `M-CONSOLE` |

That is 37 new clauses and 5 amended clauses.

**Breaking obligations** (base §4.7):
- **CT-CONF v2.0:** re-verify `M-PROV`, `M-INGEST`, `M-SETUP`, `M-ORCH`, `M-STATS`, `M-CONFORM`, `M-CONSOLE`, `M-PIPE`.
- **CT-JUDGE v2.0:** re-verify `M-INTEG`, `M-AGG`, `M-STATS`, `M-PIPE`, and the contract doubles in `tests/support/*_vocabulary.py` that construct `ScoringResult`/`StoredVerdict`.

**Safety properties touched:** none weakened. CT-JUDGE-02/03, CT-PROV-15 and CT-CONF-14 are extended to the new surface, each argued in ADR-20/25.

---

## 5. Directive → design traceability

| Directive element | Design elements | Existing cases affected (for `/create-test-plan` to reconcile) |
|---|---|---|
| "Use Jev to power our graders and evaluators (M-JUDGE, M-GRADE)" | §3.3 (FR-JUDGE-22…37); §3.6 (FR-GRADE-19, the correction in §1.1) | `tests/**/judge/*` dispatch tests keep passing with the engine off (FR-JUDGE-22) |
| "Only when Jev fails to provide a confident result (> 80%) fall back to LLM" | FR-JUDGE-27/31, CT-JUDGE-22, FR-CONF-21, ADR-20/26 | — |
| "Convert rubrics to Choice / Score / Noul" | §3.3.1, FR-JUDGE-24, ADR-22/23, FR-PROV-17 | — |
| "Everything stays the same … bias protection, orchestration, flow" | NFR-SYS-14, FR-JUDGE-25, CT-JUDGE-21/27, FR-AGG-18/19, CT-ORCH-30, CT-PIPE-09, ADR-21 | Every `RunConfig(...)` literal and `resolve_run_config` fixture (13th field / new key); `CT-CONF-C02` set-equality test; `panel_config` goldens unaffected (CT-ORCH-30) |
| "Connected → Jev on OpenRouter; local → OpenJev; separate providers" | FR-PROV-21/22/26, CT-PROV-22, FR-CONF-19, ADR-24 | `TC-PROV-*` import-graph census (CT-PROV-15) gains two classes |
| "Better grading, much faster" | NFR-JUDGE-06/07 (speed, measured), FR-STATS-26/27 + NFR-STATS-06 (quality, measured, never assumed), FR-CONFORM-10/11 | PERF suite gains `F-JEV-PERF` |
| Store-open rule | §3.10, Cohort 28/29, pin 27→29 | F-SCHEMA goldens; `COMPLETE_SCHEMA_VERSIONS` gate test; SEC-15 census line numbers |

---

## 6. Validation log: design assumptions checked against `src/aeh` at `fb12d1e`

| # | Assumption tested | Finding | Effect on the design |
|---|---|---|---|
| 1 | `M-GRADE` makes model calls to replace | **It makes none.** `grade.py:17-18`: "runs with no network, no provider and no fixtures". Only `extract`, `ingest`, `judge`, `orch`, `pipeline`, `setup`, `synth` call `.complete(` | §1.1 correction; §3.6 is a guarantee only |
| 2 | One LLM call per score unit, with a strike loop | `ScoringWorker.dispatch` (`judge.py:1832-1942`) calls `self._provider.complete` inside a strike budget, re-requests once on `ProseAssessmentError`, and propagates `RateLimited/Unavailable/BuildChanged` (`:1889`) | FR-JUDGE-31 reuses the loop unchanged; FR-JUDGE-32 mirrors the propagation |
| 3 | Where the arm's judge identity comes from | `pipeline.judge_for` (`pipeline.py:251-274`): panel member, override, or `escalation-arm-<k>` derived from the **first** arm with the build id swapped | ADR-21: without the seat rule, derived arms would inherit Jev |
| 4 | Panel sizes and base enumeration | `PANEL_SIZES = {1, 3, 5}` (`conf.py:132`); base = one score unit per panel arm; escalation widens 1→3, 3→5 (`orch.py` `enumerate_units`, `escalation_plan`) | §4.2 speedup arithmetic; Q-J1 |
| 5 | Single-judge confidence and uncited effects | `_band_position_prior` 0.50–0.75 (`agg.py:584-605`), auto-accept 0.80/0.90 (`agg.py:197-200`), uncited ×0.80 (`:202`), escalation signal weight 1.0 = threshold (`:280-296`), self-confidence weight 0.25 | FR-JUDGE-37(c) holds structurally; ADR-23 (citations are required for any speedup) |
| 6 | `RunConfig` field count is pinned | Exactly 12 fields; `CT-CONF-C02` asserts set equality (`conf.py:627-660`) | ADR-25; CT-CONF v2.0 |
| 7 | Floating tags are refused | `_has_floating_tag` (`conf.py:279`); provider-pinned form `…@<pin>` | FR-CONF-20 (`typesafe/jev-1.13@<pin>`, never `~jev-latest`) |
| 8 | Existing hosted body sends the build id verbatim as `model` | `_openai_body` sends `model_ref.build_id` (`prov.py:1127-1148`), including any `openrouter/` prefix and `@pin` | FR-PROV-21 defines the wire model explicitly for Jev. The same question for the existing LLM path is out of scope, flagged Q-J9 |
| 9 | Fixture keys are scheme-tagged | `KEY_SCHEME = b"aeh.prov/request-key/1"` (`prov.py:450`) | FR-PROV-25 uses a distinct tag, so no recorded completion fixture moves |
| 10 | Migration pins | `COMPLETE_SCHEMA_VERSIONS = {P: 12, C: 27, D: 11}` (`store.py:1479-1483`); `aeh.judge` registers Cohort 14/17/22 and Durable 9 | §3.10: Cohort 28/29 owned by `aeh.judge` |
| 11 | Band-count range vs Jev Score's 2–10 | CT-PKG-04: even, 2..6 | `band_count` ineligibility is a guard only |
| 12 | Alert-name contract | CT-ORCH-27: exactly five names | Jev alerts live in `decision_engine_metrics` (CT-JUDGE-28), not in `evaluate_alerts` |
| 13 | Run row can hold engine identity without migration | `run.provider_config` exists and is selected by `JUDGE_STATEMENTS["select_run"]` (`judge.py:367-372`) | FR-CONF-17 rehydration via `provider_config.decision_engine` |
| 16 | `discrete-gpu` can hold a decision model beside the judge (1.6's FR-CONF-23 assumed so) | **No.** HLD §8.1: 16–24 GB VRAM, "exactly one model in VRAM at a time" | FR-CONF-23 corrected; FR-CONF-28 admits only CPU placement there |
| 15 | A shipped per-profile config file exists for FR-CONF-18 to set `jev` in | **None exists.** The CLI loads an operator-supplied `--config` (`pipeline.py:1049-1060`) | FR-CONF-18 (1.6.1) adds `config/harness.example.toml` |
| 14 | Verdict row has no engine provenance | `insert_verdict` columns (`judge.py:379-387`) carry no `resolved_build` or engine | FR-JUDGE-35 / Cohort 29 |

---

## 7. Open questions

| ID | Question | Default taken here |
|---|---|---|
| Q-J1 | Should Jev-enabled runs use a **base panel of 1** (Jev seat, escalating to LLMs) to maximize speed, or keep today's configured base panel (with a 3-panel, only seat 0 is pre-screened)? | Keep the configured panel. The operator chooses. §4.2 states the trade-off |
| Q-J2 | Does OpenRouter's `/api/v1/systemone` accept `provider` preferences (zero retention, pinning)? Does `/api/alpha/decisions` keep its schema when it leaves alpha? | Decisions API by default (ADR-24). URL is a knob |
| Q-J3 | Maximum number of questions per request on each backend, and whether the OpenJev shim evaluates questions concurrently (latency scales with 2 + span count) | `max_questions = 64` (Assumption); measured by `F-JEV-PERF` |
| Q-J4 | Edge residency: can OpenJev (≥ 15 GB MLX 4-bit) co-reside with the judge on each `HARDWARE_PROFILES` entry? Does the OpenJev shim run against an MLX server that exposes top-k logprobs? | `unified-large`/`discrete-gpu` yes, `unified-small` no (FR-CONF-23). The Sweep-2a alternative of ADR-20 is the fallback design if co-residency fails |
| Q-J5 | Pass/fail thresholds for FR-CONFORM-11 (Jev vs LLM-median divergence) and NFR-STATS-06's margin δ | None for conformance. δ = 0.05 for non-inferiority (Assumption) |
| Q-J6 | Where the `decision_engine_noninferior` flag lives on `validation_record` | Inside the existing JSON payload. No Package-tier migration |
| Q-J7 | Should an engine outage be allowed to fall back to the LLM, as an explicit, run-start-frozen policy? | No (ADR-26). An outage pauses |
| Q-J8 | Later candidates for Jev beyond panel scoring: `M-INGEST` V4 semantic check (a Noul), `M-INTEG` second-family comparison assist, review-queue triage | Out of scope for this delta |
| Q-J9 | Does the existing `OpenRouterProvider` send `@pin` suffixes on the wire (validation #8)? | Not changed here. Reported for the LLM path's owner |
| Q-J10 | **OpenJev licence** (OpenJevSmall is MIT, so this applies to `openjev` only): the weights are CC BY-NC 4.0 (non-commercial). Is the deploying institution's use non-commercial, or is a commercial licence needed? | Flagged for the operator. The design does not depend on the answer, but deployment does |
| Q-J12 | **Resolved (1.7.1, user):** `openjev-small` defaults to 0.85, configurable. Original question: **the threshold for an uncalibrated engine.** OpenJevSmall's probabilities are normalised entailment, not RLCD-calibrated confidence, so `> 0.80` does not mean the same thing on it. Should `openjev-small` runs use a higher threshold until FR-STATS-27 calibrates it? | The user's 0.80 is kept. `HARNESS_JEV_CONFIDENCE_THRESHOLD` is the per-run knob. This is flagged for the user rather than changed. |
| Q-J13 | **Resolved (1.7.1, user):** 4B v5 is the build, and 2B v5 is the fallback build, chosen at configuration time (FR-CONF-27) | — |
| Q-J14 | **Resolved (1.7.1, user): accepted.** FR-CONFORM-12 stays as a measurement, and its "not recommended" flag is informational. Original question: does the user accept OpenJevSmall's documented prompt-injection weakness (0.83 → 0.47/0.44 accuracy) for base-seat verdicts on student work? | Accepted only behind FR-CONFORM-12's live measurement and the structural limits in ADR-27. The console marks a build "not recommended" when it fails. |
| Q-J11 | Should the gate be `≥ 0.80` instead of `> 0.80`? The brief says both "higher than 80%" and "drops below 80%" | Strict `>` (conservative). One-character change |

---

## Handoff

This delta is stage 1 of 4. Next:

```bash
/create-test-plan docs/design/
```

**Point it at all three design documents.** It must read the base (`detailed-design.md`), then the gap delta (`fix_gaps_detailed_design_plan.md`), then this file on top. None of them replaces another.

What the next stage should know:
- The new `CT-*` clauses are the contract and regression layer. The most consequential are:
  - CT-JUDGE-21 (seat rule) and CT-AGG-22: the guard against manufactured unanimity.
  - CT-JUDGE-22 (gate): the fallback request is byte-identical to engine-off.
  - CT-JUDGE-25 (outage vs confidence).
  - CT-JUDGE-27 (isolation and numeral scan on the new request type).
  - NFR-SYS-14: engine off means byte-identical to today, which is the anchor for "everything stays the same".
- CT-CONF v2.0 and CT-JUDGE v2.0 are breaking. Their consumer lists (§4.6) are the suites that must re-run.
- Every test story lands red under `@pytest.mark.writtenahead` until its implementing issue closes (`CLAUDE.md`).

After that, `/plan-to-issues docs/design/` should follow §4.5's landing order. Step 2's two providers are independent and can be worked in parallel.
