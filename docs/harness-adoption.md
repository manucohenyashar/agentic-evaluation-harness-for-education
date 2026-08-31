## 1. What the harness actually is

In one sentence: **a harness is a program that runs your whole system end to end on inputs you
control, and scores whether the answer was right.**

That is the entire idea. Everything else is detail. It is not a framework, not a library, and not
something you install. Three things follow from that definition, and they are what make it useful:

- **Whole system, not one function.** A unit test proves one piece works. A harness proves the
  pieces *combined* produce the right answer. This system has nineteen modules that hand work to
  each other; every one can be individually correct and the final grade can still be wrong.
- **Inputs you control.** Real student PDFs vary. The harness runs a fixed, known set of inputs
  where you already know the right answer, so a difference in output means a change in the code
  rather than a change in the data.
- **Scores the outcome.** Not "did it run without crashing" — "was the grade right, and did it
  avoid the specific wrong answers we care about".

The reason Advisor360 built this is that ViDA merged 450+ agent-written PRs in under a month with
no regressions. The harness is what made that safe. It is not overhead that slows you down; it is
the thing that lets you change code quickly without fear.

### Why the documentation is hard to read

The Confluence pages describe **three different things at once** and never fully separate them:

| Thing | What it solves | Applies here? |
|---|---|---|
| The **harness pattern** (ladder, seams, scoring) | How to test a multi-stage system end to end | **Yes — this is the part you want** |
| The **stack workspace** (symlinks, `setup.sh`, `REGISTRY.md`, tunnel ports) | Working across 7–11 separate git repos at once | **No** — this project is one repo |
| The **ephemeral Azure VM lane** (`create-vm.sh`, Bastion, tunnels) | Running heavy .NET/Kafka stacks that don't fit on a laptop | **No** — this system is Python + SQLite and fits on a laptop |

Two-thirds of the kit is machinery for problems this project does not have. That is why it reads
as impenetrable: most of it is not for you. The Confluence page says so in one line that is easy
to miss — *"A local-first stack that fits on a laptop can skip the VM parts and take only the
substrate and skills."* This project is that case.

---

## 2. What we take from the kit, and what we skip

Every file in the kit, with a verdict. The repo is 27 files / 1,415 lines, all of it read.

| File | Lines | Verdict | Why |
|---|---|---|---|
| `skills/harness-bootstrap/SKILL.md` | 92 | **Take** — copied to `.claude/skills/` | The green-field method. Exactly our situation. |
| `lib/harness/p1-bug-sweep.workflow.js` | 190 | **Take — adapt** | A **Claude Code Workflow script**, not a .NET tool. Five methodology finders (logic / adversarial / metamorphic / fuzz / error-IO) fanned out per component, then a **two-lens adversarial verify panel** that defaults to REFUTED and needs 2/2 to confirm, then synthesis. The architecture is language-agnostic; only the C# specifics in the prompt strings need retuning. See §5a. |
| `lib/harness/metamorphic.skeleton.py` | 57 | **Take as reference** — copied to `harness/reference/` | The one directly reusable code artifact. Six metamorphic relations for testing outputs you can't hardcode. |
| `skills/test-quality/SKILL.md` | 132 | **Skip the file, steal one idea** | The 7-point rubric is framework-agnostic (the skill says so itself), but adopting the file would create a second owner for test authorship, which `CLAUDE.md` forbids — `/create-test-plan` + `/write-tests` + the `reviewer` subagent already cover it, in more depth. The one idea worth taking is the **mutation-testing bar** — see §5b. |
| `conventions.md` | 21 | **Skip** | Eight bullets; five are advisor360 infrastructure (Bitbucket auth, Arnica secret scanning, the ADO NuGet feed, Azure VM P2). The two that apply — branch+PR, worktree-per-session — are already in our `CLAUDE.md`. |
| `skills/dotnet-service-harness-retrofit/SKILL.md` | 108 | **Skip** | .NET *and* retrofit-shaped. Nothing to retrofit. Its environment gotchas (SDK side-by-side, the private NuGet feed, DACPAC, Zscaler CA) are all advisor360-.NET problems. |
| `lib/common.sh`, `create-vm.sh`, `bastion-up.sh`, `bastion-tunnel.sh`, `activate-pim.sh`, `teardown-vm.sh`, `onvm.sh`, `cloud-init.base.yaml` | 215 | **Skip** | Azure ephemeral-VM lifecycle: resource groups, PIM role self-activation, Bastion tunnels, headless `az vm run-command`. We have no VM lane. |
| `lib/p2.sh`, `lib/run-svc.py` | 102 | **Skip** | Dispatcher for `local` vs `vm`, and a launcher for ASP.NET services that injects KeyVault dummies. Both .NET-shaped. |
| `lib/substrate/docker-compose.substrate.yml` | 95 | **Skip** | SQL Server, Kafka, Schema Registry, Redis, Azurite, WireMock. Our design (ADR-6) is deliberately four SQLite files and **no server process**. |
| `lib/harness/ci-coverage/` (3 files) | 114 | **Skip the code, keep the policy** | .NET coverlet + ReportGenerator + a Bitbucket pipeline. The *staging policy* is worth copying though: **enforce ≥90% on changed lines, report-only on overall, ratchet the floor up over time.** That works in any language and avoids failing every build on day one. |
| `lib/harness/stryker-rebaseline.sh` | 34 | **Skip the tool, keep the practice** | Stryker.NET. The practice — a committed mutation baseline plus a weekly scan for new survivors — ports to Python via `mutmut`. |
| `lib/harness/build-rules.sh` | 46 | **Skip** | MSBuild parallelism and symlink-path collisions. No equivalent problem in Python. |
| `lib/harness/schemathesis.sh` | 44 | **Skip for now** | OpenAPI 5xx fuzz sweep. Revisit only if `M-CONSOLE` grows an API worth fuzzing — today it is server-rendered HTML on loopback. |
| `REGISTRY.md`, `docs/EXPANSION-DESIGN.md` | 108 | **Skip — but read once** | The stack-of-stacks registry and the kit's own roadmap. No action for us, but `EXPANSION-DESIGN.md` states the principle the whole kit is built on, and it is the right one to copy: *"mechanism + templates in the kit; values/routes/suites/defs/lists in the stack."* |
| `README.md`, `.gitignore` | 57 | — | Orientation. |

**Net: three files taken** (one copied, one copied as reference, one to adapt), plus three
*policies* worth lifting without their tooling. The value is in the method, not the code — which is
what the kit's own README says: *"There is no harness framework to clone, and that is deliberate."*

---

## 3. Which playbook applies: bootstrap, not retrofit

The kit has two opposite methods. Picking the wrong one wastes weeks.

- **`harness-retrofit`** — for a system that already exists with no tests. Its first step is
  "backstop the existing code with characterization tests." Most of the work is archaeology.
- **`harness-bootstrap`** — for a system you are about to build. You design the test seams in as
  you write the code.

**This project has no application code yet.** `Code/` contains design documents, skills, and two
shell scripts — no Python, no implementation. There is nothing to retrofit and nothing to
backstop. **`harness-bootstrap` is the right method**, and it is the cheaper one: the Confluence
pages are explicit that co-evolution is the best case and retrofitting is the fallback.

This is a genuinely fortunate position. The Meeting Prep retrofit spent most of its effort on
"is this a real bug or my own scaffolding?" — an ambiguity that, per the playbook, *"barely
arises"* when you build both halves together.

---

## 4. The finding that matters: the design is already harness-shaped

The bootstrap playbook says to design in four seams on day one. **All four are already specified
in `docs/design/detailed-design.md`.** They were arrived at independently, before anyone read the
harness docs. This is not a coincidence — both documents are responding to the same problem — but
it means adoption is mostly *naming what exists*, not rebuilding.

| Harness seam (bootstrap playbook) | Already in our design as | Contract clause |
|---|---|---|
| **1. A headless driver** — one entry point that runs the system and returns a structured result + per-stage trace | `M-ORCH` (`create_run` / `start` / `progress`). The console is explicitly optional: killing it does not affect a run. | `CT-ORCH-01`, `CT-CONSOLE-01` |
| **2. A deterministic transport for every external dependency** | `M-PROV`'s **`RecordedFixtureProvider`** — keyed by a hash of the assembled request, raises rather than making a network call. Already the only egress point in the system. | `CT-PROV-10`, `CT-PROV-15` |
| **3. Env-gated knobs for every environment-sensitive constant** | Every module has a **Configuration** section; `M-CONF` freezes them into one immutable `RunConfig`. ~20 knobs already named with defaults. | `CT-CONF-11`, `CT-AGG-14` |
| **4. Stage-level observability in the result envelope** | `run_metrics`, `IngestReport.gates` (per-gate, deliberately not collapsed to a boolean), `ProgressReport`, `IntegritySignals` | `CT-ORCH-20`, `CT-INGEST-08` |

The harness's other core ideas land the same way:

| Harness idea | Already in our design |
|---|---|
| **Score the outcome, not the route** — assert what must *not* appear | `FR-CONFORM-09` pairs every adversarial submission with a **benign twin** and asserts the injection changes nothing. `FR-JUDGE-03` asserts no numeral appears in a judge prompt. |
| **Metamorphic relations** — perturb input, assert output moves correctly | `FR-STATS-15` (permute exemplar order, measure band changes), `FR-STATS-16` (replication), `FR-CONFORM-09` (twin comparison) |
| **Flake-aware gating** for non-deterministic stages | `CT-JUDGE-17` states outright that verdicts are **not reproducible**; `FR-STATS-16` measures self-agreement rather than assuming determinism |
| **L4 nightly conformance** | **`M-CONFORM` is a designed module**, with a frozen fixture set, five divergence dimensions, and declared gates |
| **Behaviour-coverage ratchets** | The `CT-*` contract clauses plus `check_traceability.py`, which fails the build when a clause has no test case |

**What this means practically:** you are not bolting a harness onto a foreign design. You are
building `M-CONFORM` and a CLI in front of it, and calling the result the harness.

---

## 5. What is genuinely missing

Four things, in the order they should be built:

1. **The runner.** A `harness` command — `harness run <case>`, `harness batch <suite.yaml>` —
   that drives `M-ORCH` on a fixture and prints a per-stage trace. This is the "headless driver"
   made usable. Small: it is a CLI over interfaces the design already specifies.
2. **The fixture corpus.** Synthetic assessments, rubrics, and student submissions with known
   correct grades. **This is the expensive part** — the Confluence page warns about it explicitly:
   *"the domain corpus is the expensive part of the whole build, because there is no generic
   synthetic-data generator to reuse."* `FR-CONFORM-01` sizes it at 30–50 submissions, and
   `FR-CONFORM-03` requires real scanned handwriting spanning legible to marginal. Budget for it.
3. **Lane wiring.** pytest markers for L0/L1/L2, so the cheap lanes run on every commit and the
   expensive ones only when asked.
4. **`TEST_CMD`.** `.claude/settings.json` currently has `"TEST_CMD": ""`, which disables the
   Stop-hook verification gate. It gets set the moment there is a suite to run.

### 5a. The bug-sweep workflow — the piece worth adapting

`lib/harness/p1-bug-sweep.workflow.js` is the one non-obvious asset in the kit, and it is not a
.NET tool at all — it is a script for the **Workflow** orchestration tool, which this project can
run as-is. Its structure:

1. **Discover** — five finders run in parallel per component, each with a different methodology:
   `logic` (wrong operators, inverted conditions, mismapped fields), `adversarial` (null/empty,
   off-by-one, locale, overflow), `metamorphic` (round-trip, order-independence, idempotence),
   `fuzz` (parsers, validators, deserializers), `errorio` (swallowed exceptions, resource leaks,
   races). Read-only — the script explicitly forbids building or running tests.
2. **Verify** — every candidate goes to a **two-lens adversarial panel** whose instruction is to
   *refute*: one lens asks "would these inputs really produce this output on the current code, or
   does a guard elsewhere prevent it?", the other asks "is this a defect or intended behaviour?"
   Default is REFUTED when uncertain; 2/2 needed to confirm.
3. **Synthesize** — dedupe, rank by severity, report per-component counts.

Why it matters here: that verify panel is the machine form of the retrofit guide's central rule —
**"a red is a hypothesis, not a finding."** And three of its five methodologies (`adversarial`,
`metamorphic`, `fuzz`) are exactly the categories our own test plan calls for and is weakest at
generating from scratch.

**To adapt:** the `METHODS` array's `focus` strings are C#-specific (AutoMapper, LINQ, `.Result`
deadlocks) and need Python/SQLite equivalents. The schemas, the read-only rules, the panel logic,
and the dedupe/rank tail need no change. Budget an hour, and run it only once there is real code.

### 5b. Mutation testing — a genuine gap in our current bar

Reading `test-quality` and `stryker-rebaseline.sh` surfaced something our pipeline does not have.
Our test plan's quality bar asks whether a case *names* the change it would catch (the `Breaks if`
field on contract cases). It never asks anyone to **prove** it. The kit does, in two places: the
retrofit bar is *"a deliberately-introduced bug anywhere in the core behavior should turn something
red"*, and Stryker measures it mechanically.

For this system that check is unusually load-bearing, because so much of the design is negative
requirements — no numeral in a judge prompt, no path from empty evidence to a low band, no even
panel. A test that fails to catch a violation of one of those is invisible in coverage.

`mutmut` or `cosmic-ray` gives the Python equivalent. Worth adding to the test plan's exit criteria
once there is a suite, scoped to the pure-function modules first (`M-AGG`, `M-DET`, `M-GRADE`,
`M-INTEG`) where it is cheapest and most meaningful.

---

## 6. The ladder, translated to this project

The kit's L0–L4 in concrete terms here. **Build the bottom rung first** — a green L3 sitting on an
unproven L0 tells you nothing.

| Rung | What it runs here | Model calls? | Speed | When |
|---|---|---|---|---|
| **L0 offline** | Pure functions with no I/O: `M-AGG.aggregate`, `M-AGG.should_escalate`, `M-DET.evaluate`, `M-GRADE.apply_policy`, `M-INTEG.verify_span`, `M-JUDGE.assemble`. The design already declares all six **pure** — that is why this rung is cheap. | none | seconds | every commit, blocks merge |
| **L1 component / contract** | The `CT-*` clause suites from the test plan — each module against its contract, plus the same cases against every test double | fixture provider | seconds | every commit |
| **L2 integrated bring-up** | The whole pipeline on one synthetic cohort, `RecordedFixtureProvider` for every model call. No network. | recorded | ~1 min | every PR |
| **L3 e2e on the synthetic corpus** | The full run — ingest → extract → integrity → judge → aggregate → grade — against a **real local model**, scored against known grades | real, local | ~10–30 min | on behaviour change; gated |
| **L4 nightly conformance** | **`M-CONFORM`**: the frozen fixture set through both backends, comparing the five divergence dimensions | real, both backends | ~1 hr | nightly |

Note where the design pays off: **L0 is unusually large here**, because so much of the system was
deliberately specified as pure functions. Most of the risky logic — confidence inversion, band
aggregation, grade policy, span verification — is testable with no model at all.

---

## 7. Will this run on Windows?

**Yes.** The parts we are taking are Markdown and Python; there is nothing platform-specific in
them. The parts that would fight Windows are the parts we are skipping.

Verified on this machine:

| Tool | Status | Needed for |
|---|---|---|
| Python 3.12 / 3.14 | installed | everything |
| `uv` 0.11 | installed | running the harness CLI (same as ViDA's `uv run harness ...`) |
| `pytest` 9.0 | installed | L0–L2 lanes |
| Git 2.51 + Git Bash | installed | the repo; running any `.sh` if ever needed |
| `gh` 2.93 | installed | the existing issue pipeline |
| Docker 28.4 | **installed, daemon stopped** | **not needed** — start it only if you later add WireMock or a containerized model server |
| WSL2 (Debian) | installed, stopped | **not needed** |
| Azure CLI | installed | **not needed** — no VM lane |

Two Windows-specific notes:

- **Symlinks.** The kit's convention is to symlink skills. Windows requires Developer Mode or an
  admin shell for that, and a symlink pointing outside the repo would not survive a clone by
  anyone else. We **copied** instead, with a provenance header naming the source commit. This is a
  deliberate deviation; re-copy when the kit changes.
- **Line endings.** If you ever do run a kit `.sh` file, run it from **Git Bash**, not PowerShell.
  If it fails with `$'\r': command not found`, the file has Windows line endings — fix with
  `dos2unix` or `sed -i 's/\r$//' <file>`.

---

## 8. Step-by-step

### Already done

```
Code/.claude/skills/harness-bootstrap/SKILL.md   # the method, with a provenance header
Code/harness/reference/metamorphic.skeleton.py   # the metamorphic pattern, as reference
Code/docs/harness-adoption.md                    # this file
```

### Step 1 — Read one page, not four

Read `.claude/skills/harness-bootstrap/SKILL.md`. It is 90 lines and it is the whole method.
Skip the Azure and stack-workspace material entirely.

### Step 2 — Finish the design pipeline first

The harness needs something to drive. The existing pipeline produces it:

```bash
cd Code && claude
```

Then, in order:

```
/create-test-plan docs/design/
```

This now generates the `CT-*` contract suites as well — which **are** the L1 rung of the ladder.
Then `/plan-to-issues docs/design/` turns both documents into issues.

### Step 3 — Build the bottom rung with the first module

Pick `M-CONF` or `M-STORE` (the design's build order starts there — §4.1). When you implement it,
implement its L0 tests in the same change. That is the co-evolution rule, and it is the only rule
that matters:

> Every new capability ships with its harness case.
> Every new external dependency ships with its deterministic seam.
> Every environment-sensitive constant ships as a knob.
> Every human-found bug becomes a permanent case.

### Step 4 — Turn the verification gate on

Once the first tests exist, set `TEST_CMD` in `.claude/settings.json`:

```json
{ "env": { "TEST_CMD": "uv run pytest -m \"not slow\"" } }
```

This re-enables the Stop hook, so no session ends claiming success without a green suite.

### Step 5 — Add the runner when there are two stages to connect

Once `M-ORCH` and one worker exist, add `harness/cli.py` with `run` and `batch`. Not before —
a runner with nothing to run is scaffolding.

### Step 6 — Build the corpus incrementally

Start with **three** synthetic submissions and grow. Do not try to build 50 up front; you will
build the wrong 50. Every bug found later becomes a permanent case (`FR-CONFORM-01`).

---

## 9. The one habit to keep

Everything above is setup. This is the practice:

**When you add a feature, add its harness case in the same change.** Not the next sprint, not "when
we get to testing" — the same change. That single habit is the difference between the ViDA outcome
(450 PRs, zero regressions) and a harness that perpetually lags behind the code as an afterthought.

The design already gives you the hooks: every `FR-*` says what must be true, every `CT-*` says what
callers may rely on, and `check_traceability.py` fails the build when either has no test.
