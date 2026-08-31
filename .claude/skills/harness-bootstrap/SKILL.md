---
name: harness-bootstrap
description: >-
  Build a test harness ALONGSIDE a new app/service/feature from day one, so the two co-evolve
  (the cheapest and strongest situation — the inverse of retrofitting, see harness-retrofit).
  Language- and stack-independent: encodes the patterns, not any test runner. A "harness" =
  a rig that drives the WHOLE assembled system through its real stages under controlled
  conditions and scores the outcome — the classic fixture-driven end-to-end bench, useful for
  ANY multi-stage system whose individually-plausible parts can combine into a wrong result
  (not just LLM systems). Trigger when: starting a new project/service, adding a substantial
  new feature/pipeline, "set up testing from scratch", "build the harness with the app", or any
  time you control the code and want to design the test seams IN rather than excavate them later.
  An agent can grow the app and its harness in one lockstep pass — this skill says how.
---

# Bootstrap the harness with the app (co-evolution)

> **Provenance.** Copied from `a360-stack-kit/skills/harness-bootstrap/SKILL.md`
> (commit `ccfeae4`). The kit's convention is to *symlink* skills so a fix lands once;
> this project copies instead, deliberately: it is a single repo with no stack workspace,
> the kit lives outside it, and Windows symlinks need Developer Mode. Re-copy from the kit
> when it changes. See `docs/harness-adoption.md` for how this project applies it.


A harness is **not** a replacement for unit/integration tests — it sits on top of the pyramid and
answers what they can't: *does the assembled system, driven end-to-end on real-shaped inputs,
produce the right outcome?* Building it alongside the app is the best case because you **design the
seams in** instead of reverse-engineering them under a deadline, and the "is this a real bug or my
own scaffolding?" ambiguity that plagues a retrofit barely arises — you built both, so you know.

## The ladder — build the bottom rung first, on day one

Stand up lanes from **fast+seeded** to **slow+fully-live**. Each rung catches a class the one below
can't. Start at L0 with the very first feature; add rungs as the system grows.

| Rung | Drives | Deps | Deterministic? | When |
|---|---|---|---|---|
| **L0 offline** | the real control flow / assembly | mocked leaves + golden inputs | yes | every commit; blocks merge |
| **L1 component/contract** | each stage + the contract between stages | seeded/stub | yes | every commit |
| **L2 integrated bring-up** | the wired system locally | local stubs of external services | mostly | per PR / on wiring change |
| **L3 e2e replay** | the whole pipeline end-to-end | a controlled/synthetic data plane | outcome-scored | on behavior change; gated |
| **L4 nightly conformance** | the full bring-up on a schedule | as-real-as-safe | tolerance-banded | nightly canary |

The cheap lanes prove logic and shape; the expensive lanes prove the real chain. Don't skip to L3 —
a green L3 on top of an unproven L0 tells you little.

## Design the seams IN (the bootstrapping advantage)

These are cheap to add on day one and painful to retrofit. Build them as you build the app:

1. **A headless driver** — one entry point that runs the whole system on a given input and returns
   a structured result + a per-stage trace. If the only way to exercise the system is the UI, you
   have no harness.
2. **A deterministic transport for every external dependency** — a stub/replay seam (record-and-replay,
   a fake server, a fixture provider) selected by config. The system must run with no real network /
   no real upstream. Add the seam the moment you add the dependency.
3. **Env-gated knobs for every environment-sensitive constant** — timeouts, page sizes, concurrency,
   retry counts, auth audiences. Default = production value; the knob exists so a slower/smaller test
   environment can adjust without a code change. (A constant calibrated for prod latency that's
   hard-coded becomes a phantom "bug" in any slower env — make it a knob now.)
4. **Stage-level observability in the result envelope** — surface what each stage did (which path,
   which deps succeeded/failed, counts) so the harness can assert on it. A bare `status=success`
   that can sit on top of an empty/wrong result is the #1 silent-failure trap; carry a
   coverage/quality signal next to the status from the start.

## What to assert

- **Score the outcome, not just the route.** Assert the final result is correct, *including what must
  NOT appear* (no silent fallback to the wrong entity, no fabricated value). A green "it took the
  right path" routinely sits on top of a wrong answer.
- **Metamorphic relations** when you can't hardcode an expected output (LLM prose, ranking, large
  aggregates): perturb the input and assert the output *moves the right way* — scale a number → the
  reported figure scales; remove a fact → it disappears; two independent inputs → no bleed between
  them. This is how you test grounding/faithfulness without a fixed golden.
- **Behaviour-coverage ratchets:** every capability/route/tool must appear in ≥1 case; every
  data-returning path must carry an outcome assertion. Adding a feature without a case fails CI.

## If a stage is non-deterministic, gate flake-aware

Real models (and some real services) flake. Don't fail the build on one red run, or the gate gets
ignored. Use: **(1)** aggregate floors per suite (catch broad collapse), **(2)** a per-case baseline
so the gate fails only on a *regression* from known-good (and a deliberate change updates the
baseline in the same change-set — no silent drift), **(3)** flake adjudication — re-run only the
suspect cases N× and classify FLAKE / CONFIRMED / UNSTABLE by reproduce rate. An ~half-passing case
is a *fragility defect*, not "fine."

## The co-evolution discipline (the actual point)

Hold every change to this rule, so the harness never lags as an afterthought:

- **Every new capability ships with its harness case** (golden or metamorphic) in the same change.
- **Every new external dependency ships with its deterministic seam.**
- **Every environment-sensitive constant ships as a knob** (prod-safe default).
- **Every human-found bug becomes a permanent case** so it can't silently return.

**For an agent:** you can hold the app and the harness in one working context and evolve them in
lockstep — when you add the feature, add its case; when you add a dep, add its fake; when you find a
constant is env-sensitive, make it a knob the same pass. Do that. The harness becomes a co-grown
twin rather than a retrofit. (Inverse skill, for systems that already exist: **harness-retrofit**.)
